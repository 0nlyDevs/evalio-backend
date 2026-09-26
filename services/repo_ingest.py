"""Repository ingestion: clone, filter, measure, detect the stack, read the git
timeline and index the source code into the vector store.

The resulting "snapshot" is plain JSON so it can be stored on the project and
shown to judges (human or AI) as hard evidence next to the LLM opinions.
"""

import json
import logging
import os
import re
import shutil
import signal
import subprocess
import tempfile
from collections import Counter, defaultdict
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import PurePosixPath
from urllib.parse import quote, urlparse

import tomllib

from config import settings
from services import vectorstore
from services.watchdog import run_with_timeout

log = logging.getLogger(__name__)

ALLOWED_HOSTS = {"github.com", "gitlab.com", "bitbucket.org"}

SKIP_DIRS = {
    "node_modules", "vendor", "dist", "build", "out", ".next", ".nuxt", ".svelte-kit",
    "target", "__pycache__", ".venv", "venv", "env", ".git", "coverage", ".turbo",
    ".cache", "bower_components", "Pods", ".gradle", ".idea", ".vscode", "site-packages",
    ".dart_tool", ".expo", "storybook-static", "public/build",
}
LOCK_FILES = {
    "package-lock.json", "yarn.lock", "pnpm-lock.yaml", "bun.lockb", "bun.lock",
    "poetry.lock", "Pipfile.lock", "uv.lock", "Cargo.lock", "composer.lock",
    "Gemfile.lock", "go.sum", "pubspec.lock", "packages.lock.json", "flake.lock",
}
BINARY_EXT = {
    ".png", ".jpg", ".jpeg", ".gif", ".webp", ".ico", ".bmp", ".tiff", ".psd", ".svgz",
    ".mp3", ".mp4", ".wav", ".ogg", ".webm", ".mov", ".avi", ".flac",
    ".woff", ".woff2", ".ttf", ".otf", ".eot",
    ".zip", ".tar", ".gz", ".tgz", ".rar", ".7z", ".jar", ".war", ".whl",
    ".pdf", ".doc", ".docx", ".xls", ".xlsx", ".ppt", ".pptx",
    ".exe", ".dll", ".so", ".dylib", ".bin", ".o", ".a", ".class", ".pyc",
    ".db", ".sqlite", ".sqlite3", ".pkl", ".pt", ".pth", ".onnx", ".h5", ".npy", ".npz",
    ".parquet", ".avro", ".map", ".lockb",
}

LANGUAGES = {
    ".py": "Python", ".ipynb": "Jupyter", ".js": "JavaScript", ".jsx": "JavaScript",
    ".mjs": "JavaScript", ".cjs": "JavaScript", ".ts": "TypeScript", ".tsx": "TypeScript",
    ".vue": "Vue", ".svelte": "Svelte", ".astro": "Astro", ".java": "Java", ".kt": "Kotlin",
    ".kts": "Kotlin", ".go": "Go", ".rs": "Rust", ".rb": "Ruby", ".php": "PHP",
    ".cs": "C#", ".fs": "F#", ".swift": "Swift", ".m": "Objective-C", ".dart": "Dart",
    ".c": "C", ".h": "C", ".cpp": "C++", ".cc": "C++", ".hpp": "C++", ".scala": "Scala",
    ".ex": "Elixir", ".exs": "Elixir", ".erl": "Erlang", ".hs": "Haskell", ".lua": "Lua",
    ".r": "R", ".jl": "Julia", ".sol": "Solidity", ".zig": "Zig", ".sh": "Shell",
    ".bash": "Shell", ".ps1": "PowerShell", ".sql": "SQL", ".html": "HTML", ".css": "CSS",
    ".scss": "SCSS", ".sass": "SCSS", ".less": "CSS", ".graphql": "GraphQL", ".proto": "Protobuf",
    ".tf": "Terraform", ".md": "Markdown", ".mdx": "Markdown", ".yml": "YAML", ".yaml": "YAML",
    ".json": "JSON", ".toml": "TOML", ".xml": "XML", ".gradle": "Gradle",
}
NON_CODE_LANGUAGES = {"Markdown", "YAML", "JSON", "TOML", "XML"}

MANIFESTS = {
    "package.json", "requirements.txt", "pyproject.toml", "setup.py", "Pipfile", "go.mod",
    "Cargo.toml", "pom.xml", "build.gradle", "build.gradle.kts", "Gemfile", "composer.json",
    "pubspec.yaml", "mix.exs", "deno.json",
}

# dependency name (lower-case) -> (project_type id, label)
FRAMEWORK_SIGNATURES: list[tuple[str, str, str]] = [
    ("next", "NEXT_JS", "Next.js"),
    ("nuxt", "NUXT", "Nuxt"),
    ("@sveltejs/kit", "SVELTEKIT", "SvelteKit"),
    ("@remix-run/react", "REMIX", "Remix"),
    ("@remix-run/node", "REMIX", "Remix"),
    ("astro", "ASTRO", "Astro"),
    ("@angular/core", "ANGULAR", "Angular"),
    ("react-native", "REACT_NATIVE", "React Native"),
    ("expo", "EXPO", "Expo"),
    ("@ionic/core", "IONIC", "Ionic"),
    ("@ionic/react", "IONIC", "Ionic"),
    ("@ionic/angular", "IONIC", "Ionic"),
    ("@nativescript/core", "NATIVESCRIPT", "NativeScript"),
    ("vue", "VUE", "Vue"),
    ("svelte", "SVELTE", "Svelte"),
    ("react", "REACT", "React"),
    ("tailwindcss", "TAILWIND", "Tailwind CSS"),
    ("express", "NODE_EXPRESS", "Express"),
    ("fastify", "NODE_EXPRESS", "Fastify"),
    ("@nestjs/core", "NODE_EXPRESS", "NestJS"),
    ("hono", "NODE_EXPRESS", "Hono"),
    ("fastapi", "FASTAPI", "FastAPI"),
    ("django", "DJANGO", "Django"),
    ("flask", "OTHER", "Flask"),
    ("streamlit", "OTHER", "Streamlit"),
    ("gradio", "OTHER", "Gradio"),
    ("spring-boot-starter", "SPRING_BOOT", "Spring Boot"),
    ("spring-boot-starter-web", "SPRING_BOOT", "Spring Boot"),
    ("github.com/gin-gonic/gin", "GIN", "Gin"),
    ("rails", "RAILS", "Rails"),
    ("laravel/framework", "LARAVEL", "Laravel"),
    ("actix-web", "ACTIX", "Actix"),
    ("flutter", "FLUTTER", "Flutter"),
    ("microsoft.maui.controls", "DOTNET_MAUI", ".NET MAUI"),
    ("androidx.compose.ui:ui", "KOTLIN_JETPACK", "Jetpack Compose"),
]

NOTABLE_LIBRARIES = {
    "openai": "OpenAI", "anthropic": "Anthropic", "@anthropic-ai/sdk": "Anthropic",
    "langchain": "LangChain", "@langchain/core": "LangChain", "llama-index": "LlamaIndex",
    "transformers": "Transformers", "torch": "PyTorch", "tensorflow": "TensorFlow",
    "scikit-learn": "scikit-learn", "pandas": "pandas", "numpy": "NumPy",
    "@google/generative-ai": "Gemini", "google-generativeai": "Gemini",
    "prisma": "Prisma", "@prisma/client": "Prisma", "drizzle-orm": "Drizzle",
    "sqlalchemy": "SQLAlchemy", "mongoose": "MongoDB", "pymongo": "MongoDB",
    "mongodb": "MongoDB", "pg": "PostgreSQL", "psycopg2": "PostgreSQL",
    "psycopg2-binary": "PostgreSQL", "psycopg": "PostgreSQL", "redis": "Redis",
    "@supabase/supabase-js": "Supabase", "supabase": "Supabase", "firebase": "Firebase",
    "firebase-admin": "Firebase", "stripe": "Stripe", "socket.io": "Socket.IO",
    "graphql": "GraphQL", "@apollo/client": "Apollo", "trpc": "tRPC", "@trpc/server": "tRPC",
    "zod": "Zod", "pydantic": "Pydantic", "celery": "Celery", "chromadb": "ChromaDB",
    "pinecone-client": "Pinecone", "@pinecone-database/pinecone": "Pinecone",
    "three": "Three.js", "d3": "D3", "web3": "Web3", "ethers": "ethers.js",
    "hardhat": "Hardhat", "solana-web3.js": "Solana", "@solana/web3.js": "Solana",
    "jest": "Jest", "vitest": "Vitest", "pytest": "pytest", "cypress": "Cypress",
    "playwright": "Playwright", "@playwright/test": "Playwright", "docker": "Docker",
    "clerk": "Clerk", "@clerk/nextjs": "Clerk", "next-auth": "NextAuth", "auth0": "Auth0",
    "@tanstack/react-query": "TanStack Query", "redux": "Redux", "zustand": "Zustand",
}

TEST_PATTERN = re.compile(r"(^|/)(tests?|__tests__|spec|specs)(/|$)|(\.|_)(test|spec)\.[a-z]+$|^test_.*\.py$|/test_[^/]*\.py$", re.I)


SECRET_PATTERNS = [
    ("OpenAI API key", re.compile(r"sk-(?:proj-)?[A-Za-z0-9_-]{32,}")),
    ("Anthropic API key", re.compile(r"sk-ant-[A-Za-z0-9_-]{32,}")),
    ("AWS access key", re.compile(r"AKIA[0-9A-Z]{16}")),
    ("GitHub token", re.compile(r"gh[pousr]_[A-Za-z0-9]{36,}")),
    ("Google API key", re.compile(r"AIza[0-9A-Za-z_-]{35}")),
    ("Stripe secret key", re.compile(r"sk_live_[0-9A-Za-z]{24,}")),
    ("Slack token", re.compile(r"xox[baprs]-[0-9A-Za-z-]{10,}")),
    ("Private key", re.compile(r"-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----")),
    ("Database URL with password", re.compile(r"(?:postgres(?:ql)?|mysql|mongodb(?:\+srv)?)://[^:\s/]+:[^@\s]{4,}@(?!localhost|127\.0\.0\.1|db[:/]|postgres[:/])")),
]


def _scan_secrets(texts: dict[str, str], limit: int = 10) -> list[dict]:
    findings = []
    for path, text in texts.items():
        lower = path.lower()
        if lower.endswith((".md", ".example", ".sample", ".template")) or "example" in lower:
            continue
        if TEST_PATTERN.search(path) or "fixture" in lower or "mock" in lower:
            continue  # test certificates / fake keys
        for line_no, line in enumerate(text.splitlines(), start=1):
            for kind, pattern in SECRET_PATTERNS:
                if pattern.search(line):
                    findings.append({"path": path, "line": line_no, "kind": kind})
                    break
            if len(findings) >= limit:
                return findings
    return findings


class IngestError(RuntimeError):
    pass


@dataclass
class RepoRef:
    host: str
    owner: str
    name: str

    @property
    def url(self) -> str:
        return f"https://{self.host}/{self.owner}/{self.name}"


def parse_repo_url(url: str) -> RepoRef:
    raw = (url or "").strip()
    if not raw:
        raise IngestError("Repository URL is empty")
    if not re.match(r"^https?://", raw, re.I):
        raw = "https://" + raw
    parsed = urlparse(raw)
    host = (parsed.hostname or "").lower().removeprefix("www.")
    if host not in ALLOWED_HOSTS:
        raise IngestError(f"Only {', '.join(sorted(ALLOWED_HOSTS))} repositories are supported")
    parts = [p for p in parsed.path.split("/") if p]
    if len(parts) < 2:
        raise IngestError("Repository URL must look like https://github.com/<owner>/<repo>")
    owner, name = parts[0], parts[1].removesuffix(".git")
    if not re.fullmatch(r"[A-Za-z0-9_.-]+", owner) or not re.fullmatch(r"[A-Za-z0-9_.-]+", name):
        raise IngestError("Repository owner or name contains invalid characters")
    return RepoRef(host=host, owner=owner, name=name)


def _clone_url(ref: RepoRef) -> str:
    if ref.host == "github.com" and settings.github_token:
        return f"https://x-access-token:{quote(settings.github_token, safe='')}@github.com/{ref.owner}/{ref.name}.git"
    return f"{ref.url}.git"


def _kill_group(proc: subprocess.Popen) -> None:
    """Kill `git` and any helper it spawned (git-remote-https...).

    A plain `proc.kill()` leaves those children alive holding the pipe, so a
    stalled clone can block on `communicate()` well past its timeout.
    """
    try:
        os.killpg(os.getpgid(proc.pid), signal.SIGKILL)
    except (ProcessLookupError, PermissionError, OSError):
        proc.kill()


def _git(args: list[str], cwd: str | None = None, timeout: int = 60) -> str:
    env = {**os.environ, "GIT_TERMINAL_PROMPT": "0", "GIT_LFS_SKIP_SMUDGE": "1"}
    proc = subprocess.Popen(
        ["git", *args], cwd=cwd, env=env, text=True,
        stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
        start_new_session=True,  # own process group, so we can kill the whole tree
    )
    try:
        out, err = proc.communicate(timeout=timeout)
    except subprocess.TimeoutExpired as exc:
        _kill_group(proc)
        try:
            proc.communicate(timeout=5)  # reap the killed process tree
        except subprocess.TimeoutExpired:
            pass
        raise IngestError(f"git {args[0]} timed out after {timeout}s") from exc
    if proc.returncode != 0:
        message = (err or out).strip()
        if settings.github_token:
            message = message.replace(settings.github_token, "***")
        raise IngestError(message.splitlines()[-1] if message else "git failed")
    return out


def clone(ref: RepoRef, dest: str) -> None:
    try:
        _git(
            [
                "clone", "--depth", str(settings.repo_history_depth), "--single-branch",
                "--no-tags", "--quiet", _clone_url(ref), dest,
            ],
            timeout=settings.repo_clone_timeout,
        )
    except IngestError as exc:
        text = str(exc).lower()
        if "not found" in text or "could not read username" in text or "authentication" in text:
            raise IngestError(
                "Repository not found or private. Make it public or configure GITHUB_TOKEN."
            ) from exc
        raise


# ---------------------------------------------------------------------------
# File inventory
# ---------------------------------------------------------------------------


def _is_skipped(path: str) -> bool:
    parts = PurePosixPath(path).parts
    if any(p in SKIP_DIRS for p in parts[:-1]):
        return True
    name = parts[-1]
    if name in LOCK_FILES:
        return True
    lower = name.lower()
    if lower.endswith((".min.js", ".min.css", ".bundle.js", ".chunk.js")):
        return True
    return PurePosixPath(lower).suffix in BINARY_EXT


def _read_text(abs_path: str, max_bytes: int) -> str | None:
    try:
        size = os.path.getsize(abs_path)
        if size > max_bytes or size == 0:
            return None
        with open(abs_path, "rb") as fh:
            data = fh.read()
        if b"\x00" in data[:8192]:
            return None
        text = data.decode("utf-8", errors="replace")
        lines = text.splitlines() or [""]
        if len(text) / max(1, len(lines)) > 400:  # minified / generated
            return None
        return text
    except OSError:
        return None


def _language(path: str) -> str | None:
    name = PurePosixPath(path).name
    if name == "Dockerfile" or name.startswith("Dockerfile."):
        return "Dockerfile"
    if name == "Makefile":
        return "Makefile"
    return LANGUAGES.get(PurePosixPath(path).suffix.lower())


def _file_priority(path: str) -> tuple[int, int, str]:
    p = PurePosixPath(path)
    lower = p.name.lower()
    depth = len(p.parts)
    if lower.startswith("readme"):
        rank = 0
    elif p.name in MANIFESTS:
        rank = 1
    elif TEST_PATTERN.search(path):
        rank = 3
    elif _language(path) in NON_CODE_LANGUAGES or lower.endswith((".md", ".txt", ".rst")):
        rank = 4
    else:
        rank = 2
    return rank, depth, path


# ---------------------------------------------------------------------------
# Dependencies & stack detection
# ---------------------------------------------------------------------------


def _parse_dependencies(files: dict[str, str]) -> dict[str, list[str]]:
    deps: dict[str, list[str]] = defaultdict(list)

    for path, text in files.items():
        name = PurePosixPath(path).name
        try:
            if name == "package.json":
                data = json.loads(text)
                for key in ("dependencies", "devDependencies", "peerDependencies"):
                    deps["npm"].extend((data.get(key) or {}).keys())
            elif name == "requirements.txt":
                for line in text.splitlines():
                    line = line.split("#")[0].strip()
                    if line and not line.startswith("-"):
                        deps["pip"].append(re.split(r"[<>=!~\[; ]", line)[0])
            elif name == "pyproject.toml":
                data = tomllib.loads(text)
                project = data.get("project", {})
                for dep in project.get("dependencies", []) or []:
                    deps["pip"].append(re.split(r"[<>=!~\[; ]", dep)[0])
                poetry = data.get("tool", {}).get("poetry", {})
                deps["pip"].extend(k for k in (poetry.get("dependencies") or {}) if k != "python")
            elif name == "Pipfile":
                deps["pip"].extend(re.findall(r'^([A-Za-z0-9_.-]+)\s*=', text, re.M))
            elif name == "go.mod":
                deps["go"].extend(re.findall(r"^\s*([a-z0-9.\-]+/[^\s]+)\s+v", text, re.M))
            elif name == "Cargo.toml":
                data = tomllib.loads(text)
                deps["cargo"].extend((data.get("dependencies") or {}).keys())
            elif name == "pom.xml":
                deps["maven"].extend(re.findall(r"<artifactId>([^<]+)</artifactId>", text))
            elif name in ("build.gradle", "build.gradle.kts"):
                deps["gradle"].extend(
                    m.split(":")[0] + ":" + m.split(":")[1] if m.count(":") >= 1 else m
                    for m in re.findall(r"""["']([\w.\-]+:[\w.\-]+)(?::[^"']*)?["']""", text)
                )
            elif name == "Gemfile":
                deps["gem"].extend(re.findall(r"""^\s*gem\s+["']([^"']+)["']""", text, re.M))
            elif name == "composer.json":
                data = json.loads(text)
                deps["composer"].extend((data.get("require") or {}).keys())
            elif name == "pubspec.yaml":
                deps["pub"].extend(re.findall(r"^\s{2}([a-z_][a-z0-9_]*):", text, re.M))
            elif name.endswith(".csproj"):
                deps["nuget"].extend(re.findall(r'PackageReference\s+Include="([^"]+)"', text))
        except (ValueError, tomllib.TOMLDecodeError, KeyError, IndexError):
            continue

    return {k: sorted({d.strip().lower() for d in v if d and d.strip()}) for k, v in deps.items()}


def _detect_stack(deps: dict[str, list[str]], paths: list[str], source_texts: dict[str, str]) -> dict:
    all_deps = {d for values in deps.values() for d in values}
    frameworks: list[dict] = []
    seen_labels: set[str] = set()

    def add(type_id: str, label: str):
        if label not in seen_labels:
            seen_labels.add(label)
            frameworks.append({"id": type_id, "label": label})

    for dep, type_id, label in FRAMEWORK_SIGNATURES:
        if dep in all_deps or any(d.startswith(dep + ":") for d in all_deps):
            add(type_id, label)
    is_flutter = "flutter" in deps.get("pub", [])
    if is_flutter or (any(p.endswith("pubspec.yaml") for p in paths) and any(p.endswith(".dart") for p in paths)):
        add("FLUTTER", "Flutter")
    if any(p.endswith(".swift") for p in paths) and any("import SwiftUI" in t for p, t in source_texts.items() if p.endswith(".swift")):
        add("SWIFT_UI", "SwiftUI")
    if any("androidx.compose" in d for d in all_deps):
        add("KOTLIN_JETPACK", "Jetpack Compose")
    if any("rails" == d for d in deps.get("gem", [])):
        add("RAILS", "Rails")

    libraries = sorted({label for dep, label in NOTABLE_LIBRARIES.items() if dep in all_deps})
    has_frontend_only = bool(frameworks) and all(
        f["id"] in {"REACT", "VUE", "SVELTE", "ANGULAR", "TAILWIND", "ASTRO", "VANILLA_JS"} for f in frameworks
    )
    if not frameworks and any(p.endswith(".html") for p in paths) and any(p.endswith(".js") for p in paths):
        add("VANILLA_JS", "Vanilla JS")

    return {
        "frameworks": frameworks,
        "libraries": libraries,
        "primary_type": frameworks[0]["id"] if frameworks else "OTHER",
        "frontend_only": has_frontend_only,
    }


# ---------------------------------------------------------------------------
# Git history
# ---------------------------------------------------------------------------


def _git_history(repo_dir: str) -> dict:
    try:
        out = _git(
            ["log", f"-n{settings.repo_history_depth}", "--format=%H%x1f%an%x1f%ae%x1f%aI%x1f%s"],
            cwd=repo_dir,
        )
    except IngestError:
        return {"commit_count": 0, "commits": [], "contributors": [], "truncated": False}

    commits = []
    for line in out.splitlines():
        parts = line.split("\x1f")
        if len(parts) != 5:
            continue
        sha, author, email, date, subject = parts
        commits.append({"sha": sha[:10], "author": author, "email": email.lower(), "date": date, "subject": subject[:140]})

    authors = Counter(c["email"] or c["author"] for c in commits)
    names = {c["email"] or c["author"]: c["author"] for c in commits}
    per_day = Counter(c["date"][:10] for c in commits)
    subjects = [c["subject"] for c in commits]
    low_quality = sum(
        1 for s in subjects
        if len(s) < 8 or s.lower().strip(". ") in {"update", "fix", "wip", "changes", "commit", "initial commit", "first commit", "test", "."}
    )
    return {
        "commit_count": len(commits),
        "truncated": len(commits) >= settings.repo_history_depth,
        "first_commit_at": commits[-1]["date"] if commits else None,
        "last_commit_at": commits[0]["date"] if commits else None,
        "contributors": [{"name": names[k], "commits": v} for k, v in authors.most_common(10)],
        "commits_per_day": dict(sorted(per_day.items())),
        "low_quality_messages": low_quality,
        "recent_commits": [
            {k: c[k] for k in ("sha", "author", "date", "subject")} for c in commits[:15]
        ],
        "commit_dates": [c["date"] for c in commits],
    }


# ---------------------------------------------------------------------------
# Chunking
# ---------------------------------------------------------------------------


def _chunk_file(path: str, text: str, language: str | None, max_lines: int = 70, overlap: int = 8, max_chars: int = 2400) -> list[dict]:
    lines = text.splitlines()
    chunks = []
    start = 0
    while start < len(lines):
        end = min(len(lines), start + max_lines)
        body = "\n".join(lines[start:end])
        while len(body) > max_chars and end - start > 10:
            end = start + max(10, (end - start) // 2)
            body = "\n".join(lines[start:end])
        if body.strip():
            chunks.append({
                "id": f"{path}:{start + 1}",
                "text": f"File: {path}\n{body[:max_chars]}",
                "metadata": {
                    "path": path,
                    "start_line": start + 1,
                    "end_line": end,
                    "language": language or "Text",
                    "kind": "doc" if (language in NON_CODE_LANGUAGES or language is None) else "code",
                },
            })
        if end >= len(lines):
            break
        start = end - overlap
    return chunks


def _tree(paths: list[str], max_entries: int = 160) -> str:
    """Compact directory tree (dirs up to depth 3 with file counts)."""
    dirs: Counter = Counter()
    top_files = []
    for p in paths:
        parts = PurePosixPath(p).parts
        if len(parts) == 1:
            top_files.append(p)
        for depth in range(1, min(len(parts), 4)):
            dirs["/".join(parts[:depth]) + "/"] += 1
    lines = sorted(top_files)[:40]
    lines += [f"{d} ({n} files)" for d, n in sorted(dirs.items())]
    if len(lines) > max_entries:
        lines = lines[:max_entries] + [f"... {len(lines) - max_entries} more"]
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------


def ingest_repository(url: str, project_id: str | None = None, index: bool = True) -> dict:
    """Clone + analyse a repository. Indexes code into Chroma when `project_id` is given."""
    ref = parse_repo_url(url)
    workdir = tempfile.mkdtemp(prefix="evalio-")
    repo_dir = os.path.join(workdir, "repo")
    try:
        clone(ref, repo_dir)
        head = _git(["rev-parse", "HEAD"], cwd=repo_dir).strip()
        branch = _git(["rev-parse", "--abbrev-ref", "HEAD"], cwd=repo_dir).strip()
        tracked = [p for p in _git(["ls-files", "-z"], cwd=repo_dir).split("\x00") if p]
        return _analyse_checkout(ref, repo_dir, tracked, head, branch, project_id, index)
    finally:
        shutil.rmtree(workdir, ignore_errors=True)


def _analyse_checkout(ref, repo_dir, tracked, head, branch, project_id, index) -> dict:
    max_bytes = settings.repo_max_file_kb * 1024
    candidates = sorted((p for p in tracked if not _is_skipped(p)), key=_file_priority)
    candidates = candidates[: settings.repo_max_files]

    texts: dict[str, str] = {}
    loc_by_language: Counter = Counter()
    files_by_language: Counter = Counter()
    largest: list[tuple[int, str]] = []
    for path in candidates:
        text = _read_text(os.path.join(repo_dir, path), max_bytes)
        if text is None:
            continue
        texts[path] = text
        language = _language(path)
        loc = sum(1 for line in text.splitlines() if line.strip())
        if language:
            loc_by_language[language] += loc
            files_by_language[language] += 1
        largest.append((loc, path))

    code_paths = [p for p in texts if (_language(p) or "") not in NON_CODE_LANGUAGES and _language(p)]
    code_loc = sum(v for k, v in loc_by_language.items() if k not in NON_CODE_LANGUAGES)
    test_files = [p for p in code_paths if TEST_PATTERN.search(p)]
    readme_path = next((p for p in texts if PurePosixPath(p).name.lower().startswith("readme") and len(PurePosixPath(p).parts) == 1), None)
    readme = texts.get(readme_path, "") if readme_path else ""

    manifests = {p: t for p, t in texts.items() if PurePosixPath(p).name in MANIFESTS or p.endswith(".csproj")}
    deps = _parse_dependencies(manifests)
    stack = _detect_stack(deps, list(texts), {p: texts[p] for p in code_paths[:200]})

    lower_paths = [p.lower() for p in tracked]
    has = lambda *needles: any(any(n in p for n in needles) for p in lower_paths)  # noqa: E731
    signals = {
        "has_readme": bool(readme),
        "readme_chars": len(readme),
        "readme_sections": len(re.findall(r"^#{1,3} ", readme, re.M)),
        "has_tests": bool(test_files),
        "test_files": len(test_files),
        "has_ci": has(".github/workflows/", ".gitlab-ci.yml", ".circleci/", "azure-pipelines", "jenkinsfile"),
        "has_docker": has("dockerfile", "docker-compose", "compose.yaml", "compose.yml"),
        "has_license": any(PurePosixPath(p).name.lower().startswith(("license", "licence")) for p in tracked),
        "has_env_example": has(".env.example", ".env.sample", ".env.template"),
        "has_linter": has("eslint", ".prettierrc", "ruff.toml", ".flake8", ".pylintrc", "biome.json", ".golangci", "rustfmt.toml", ".editorconfig"),
        "has_type_checking": has("tsconfig.json", "mypy.ini", "pyrightconfig.json", "py.typed"),
        "has_gitignore": ".gitignore" in tracked,
        "committed_secrets_risk": [p for p in tracked if PurePosixPath(p).name in {".env", ".env.local", ".env.production", "credentials.json", "serviceAccountKey.json"}][:5],
        "hardcoded_secrets": _scan_secrets(texts),
        "committed_dependencies": any(p.startswith("node_modules/") or "/node_modules/" in p for p in tracked[:5000]),
    }

    history = _git_history(repo_dir)

    snapshot = {
        "repo": {"url": ref.url, "owner": ref.owner, "name": ref.name, "host": ref.host, "branch": branch, "commit": head[:12]},
        "ingested_at": datetime.now(timezone.utc).isoformat(),
        "files": {
            "tracked": len(tracked),
            "analyzed": len(texts),
            "code_files": len(code_paths),
            "code_loc": code_loc,
            "skipped": len(tracked) - len(texts),
        },
        "languages": [
            {"name": lang, "loc": loc, "files": files_by_language[lang], "share": round(loc / max(1, sum(loc_by_language.values())), 3)}
            for lang, loc in loc_by_language.most_common(12)
        ],
        "largest_files": [{"path": p, "loc": n} for n, p in sorted(largest, reverse=True)[:8]],
        "dependencies": {k: v[:80] for k, v in deps.items()},
        "stack": stack,
        "signals": signals,
        "history": history,
        "tree": _tree(list(texts)),
        "readme": readme[:12000],
        "manifests": {p: t[:3000] for p, t in list(manifests.items())[:6]},
        "indexed_chunks": 0,
    }

    if index and project_id:
        # Indexing is best effort: a slow or stuck embedder must never block
        # ingestion, so the judges still get the measured snapshot and the
        # project still reaches a verdict.
        try:
            count, truncated = run_with_timeout(
                lambda: _index_texts(project_id, texts),
                settings.index_timeout,
                label="code-index",
            )
            snapshot["indexed_chunks"] = count
            snapshot["index_truncated"] = truncated
            log.info("Indexed %s chunks from %s for project %s", count, ref.url, project_id)
        except Exception as exc:
            log.warning("Could not index %s (continuing without a code index): %s", ref.url, exc)

    return snapshot


def _index_texts(project_id: str, texts: dict[str, str]) -> tuple[int, bool]:
    """Chunk the (priority-ordered) source files and store them in Chroma."""
    chunks: list[dict] = []
    for path, text in texts.items():
        if len(chunks) >= settings.repo_max_chunks:
            break
        chunks.extend(_chunk_file(path, text, _language(path)))
    chunks = chunks[: settings.repo_max_chunks]
    collection = vectorstore.reset_code_collection(project_id)
    vectorstore.add_chunks(collection, chunks)
    return len(chunks), len(chunks) >= settings.repo_max_chunks
