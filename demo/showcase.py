"""Showcase content: example evaluations of real public repositories.

Repository snapshots, web sources and demo checks in `demo/data/*.json` were
produced by Evalio's own ingestion, web search and demo probe. The judges'
written assessments below were prepared from those measurements and the
source code; scorecards, weighted final scores and integrity flags are
computed by the jury's code at seed time (see demo/seed.py).
"""

SHOWCASE = {
    "name": "Evalio Showcase: Build Something Real",
    "description": (
        "Example evaluations that show how the Evalio jury works. Each project below was cloned, "
        "measured and indexed, researched on the web, and judged by the Code, Market and Product "
        "judges. Explore the reports, then submit your own project to the Open Sandbox."
    ),
    "theme": "AI, Developer tools, Real-time, Open data",
    "technologies": "TypeScript, Python",
    "starts_at": "2025-09-01T00:00:00+00:00",
    "deadline": "2026-09-25T23:59:00+00:00",
    "criteria": [
        {"name": "Technical Execution", "weight": 30, "judge": "code",
         "description": "Quality, architecture, tests and robustness of the implementation."},
        {"name": "Innovation", "weight": 20, "judge": "product",
         "description": "Originality compared with existing products and other submissions."},
        {"name": "Market Potential", "weight": 20, "judge": "market",
         "description": "Size of the opportunity, differentiation and business viability."},
        {"name": "UX & Presentation", "weight": 15, "judge": "product",
         "description": "Interface, onboarding, documentation and live demo."},
        {"name": "Completeness", "weight": 15, "judge": "product",
         "description": "How much of what the team claims is actually built."},
    ],
}

SANDBOX = {
    "name": "Open Sandbox",
    "description": (
        "Try Evalio on your own work: submit any public GitHub repository and watch the jury clone it, "
        "read the code, research the market and rank it."
    ),
    "theme": "Anything",
    "technologies": "",
    "criteria": None,  # default criteria
}

PROJECTS = [
    # ------------------------------------------------------------------ KOKORO
    {
        "key": "kokoro",
        "name": "KOKORO",
        "short": "Watch YouTube together with friends, in sync, while you chat in real time.",
        "long": (
            "Kokoro is a real-time space to chat and watch videos together. Rooms keep YouTube playback in sync "
            "for every member, friends get live notifications for requests and invites, messages support reactions, "
            "and sign-in works with Google, GitHub or Facebook through BetterAuth. Built with Next.js, a custom "
            "Socket.IO server, Prisma and Supabase."
        ),
        "repo": "https://github.com/colombefioren/KOKORO",
        "demo_link": "https://kokoro-backend.onrender.com",
        "project_type": "NEXT_JS",
        "code": {
            "review_score": 8.3,
            "summary": (
                "A substantial full-stack TypeScript app (about 21k lines) with a clear split between a Next.js front end "
                "and a dedicated Socket.IO server. Real-time features are implemented for real: every socket is "
                "authenticated in middleware, playback state is relayed per room, and noisy events are rate limited."
            ),
            "architecture": (
                "Next.js App Router pages and 34 API routes, a custom server in server.mts for sockets, Prisma models over "
                "Supabase Postgres, Zustand stores and TanStack Query hooks per domain (chats, rooms, users)."
            ),
            "strengths": [
                "Socket connections are authenticated with a short-lived token before any event is accepted (server.mts)",
                "Per-event rate limits on change-video and update-video-state stop room spam (server.mts)",
                "Vitest suite covers video sync between members and the reaction picker (src/lib/__tests__)",
                "Commit history reads like a real product: small, well-described fixes",
            ],
            "weaknesses": [
                "server.mts has grown to 640+ lines mixing presence, voice and video logic",
                "The generated OpenAPI client (src/api/ApiClient.ts, 1.5k lines) is checked in and hard to review",
            ],
            "risks": [
                "Sync relies on the last client update winning, which can drift for large rooms on slow networks",
            ],
            "evidence": [
                {"file": "server.mts", "note": "socket auth middleware, rate limits and video state relay"},
                {"file": "prisma/schema.prisma", "note": "rooms, chats, friendships and notifications data model"},
                {"file": "src/components/room/room-panel.tsx", "note": "room UI wiring playback and members"},
                {"file": ".github/workflows/ci.yml", "note": "lint and tests run in CI"},
            ],
            "files_reviewed": [
                "server.mts", "src/api/ApiClient.ts", "src/components/chat/chat-main.tsx",
                "src/components/room/room-panel.tsx", "src/lib/db", "prisma/schema.prisma",
            ],
        },
        "market": {
            "profile": {
                "pitch": "A social watch-party space: synced YouTube rooms plus friends, chat and notifications.",
                "problem": "Watching videos together remotely usually means juggling a video link, a call and a separate chat.",
                "solution": "Persistent rooms where playback, chat, reactions and friend presence live in one place.",
                "category": "Social watch-party apps",
                "target_users": ["Friend groups and long-distance couples", "Online communities and study groups"],
            },
            "summary": (
                "Watch parties are a proven but crowded category: Teleparty, Rave, WatchTogether and many browser tools "
                "already sync playback [1][5][6]. Kokoro stands out by being a social product first, with friends, "
                "presence and persistent rooms, rather than a one-off sync link."
            ),
            "audience": [
                {"name": "Friend groups", "need": "hang out around videos without a separate call and chat app"},
                {"name": "Long-distance couples", "need": "a shared, persistent space rather than a disposable link"},
                {"name": "Communities and clubs", "need": "recurring rooms with members and notifications"},
            ],
            "problem_severity": "Real but low-urgency: users tolerate workarounds, so convenience and social features must carry adoption [6].",
            "market_size": "The broader social video platform market is estimated at USD 55.2 billion in 2025, growing to USD 120 billion by 2035 [11].",
            "market_trend": "2026 comparisons still list many no-signup sync tools, which keeps switching costs low [1][8].",
            "competitors": [
                {"name": "Teleparty", "description": "Browser extension syncing Netflix, YouTube, Disney+ and more", "differentiation": "Kokoro adds persistent rooms and a friends graph but only supports YouTube and uploads", "source": 5},
                {"name": "SyncUp", "description": "No-signup browser watch party for YouTube, Twitch and HTML5 video", "differentiation": "Kokoro requires an account but keeps history, friends and notifications", "source": 1},
                {"name": "WatchMates", "description": "Watch-party extension positioned as a Teleparty alternative", "differentiation": "Kokoro is a full web app rather than an extension", "source": 3},
                {"name": "Rave", "description": "Mobile-first social watch app", "differentiation": "Kokoro is web-first with richer chat and reactions", "source": 8},
            ],
            "differentiation": "The social layer (friends, presence, notifications, reactions) is the edge; pure sync is table stakes [7].",
            "business": {
                "business_model": "Freemium: free rooms, paid tier for larger rooms, uploads storage and custom themes.",
                "revenue_streams": ["Premium rooms", "Upload storage", "Community plans"],
                "go_to_market": ["Seed with anime and K-pop fan communities on Discord", "Shareable room links that invite friends into the app"],
                "risks": [
                    {"risk": "Crowded category with free incumbents", "severity": "high", "mitigation": "Lean into the social graph and community rooms"},
                    {"risk": "YouTube embed policy changes", "severity": "medium", "mitigation": "Keep uploads as a first-class source"},
                ],
                "opportunities": ["Study-together rooms", "Creator-hosted premieres"],
                "verdict": "Well executed in a busy space; the social features give it a credible niche.",
            },
            "scores": {"market_potential": 6.4, "differentiation": 5.8, "viability": 6.2},
        },
        "product": {
            "summary": (
                "A polished, complete product: rooms, sync, chat, reactions, friends and notifications all work together, "
                "and a live deployment is up. The idea itself is familiar, so originality is moderate."
            ),
            "scores": {"innovation": 6.2, "theme_fit": 7.8, "user_experience": 8.4},
            "rationales": {
                "innovation": "Synchronized watching is well covered by existing tools; the social layer is the fresh part.",
                "theme_fit": "Squarely in the real-time track, with a full custom socket layer.",
                "user_experience": "Thoughtful room layout, reactions and voice bar; commits show sustained UX polish.",
            },
            "wow_factor": "Friends, presence and synced playback in one persistent room.",
            "suggestions": ["Support more video sources than YouTube", "Split server.mts into presence, voice and video modules"],
            "claims": [
                {"claim": "Real-time chat and notifications", "status": "implemented", "file": "server.mts", "note": "presence and notification events emitted per friend"},
                {"claim": "Synced YouTube playback across members", "status": "implemented", "file": "server.mts", "note": "update-video-state relayed to the room with rate limiting"},
                {"claim": "Login with Google, GitHub and Facebook", "status": "implemented", "file": "src/app/api/auth/[...all]/route.ts", "note": "BetterAuth handler"},
                {"claim": "Type-safe forms with Zod", "status": "implemented", "file": "src/lib/validation", "note": "Zod schemas shared by forms and routes"},
                {"claim": "Message reactions", "status": "implemented", "file": "src/app/api/messages/[messageId]/reactions/route.ts", "note": "reactions API and picker"},
            ],
        },
        "criteria": {
            "Technical Execution": (8.2, "Solid full-stack architecture with authenticated sockets, rate limits, CI and a meaningful test suite; the socket server could be modularized."),
            "Innovation": (6.2, "Watch parties exist in many forms; the persistent social layer is the original angle."),
            "Market Potential": (6.1, "Large social video market, but crowded with free tools; community positioning is the path."),
            "UX & Presentation": (8.4, "Cohesive, polished interface with a live deployment and a clear README."),
            "Completeness": (9.0, "Every feature listed in the README maps to working code."),
        },
        "verdict": {
            "headline": "A complete, polished real-time product in a familiar category.",
            "summary": (
                "Kokoro is one of the most finished projects in the showcase: sockets, auth, sync and social features all "
                "hold up in the code, and the demo is live. It loses points on originality because watch parties are "
                "well served, and some history predates the event window."
            ),
            "strengths": ["Every claimed feature is implemented", "Authenticated, rate-limited socket layer", "Live demo and CI"],
            "improvements": ["Differentiate beyond YouTube sync", "Break up the 640-line socket server"],
        },
    },
    # ------------------------------------------------------------------ COKEY
    {
        "key": "cokey",
        "name": "COKEY",
        "short": "Pool every free LLM API behind one OpenAI-compatible endpoint with key-first failover.",
        "long": (
            "COKEY lets you chain free-tier models from 50+ providers behind a single OpenAI-compatible endpoint. Each "
            "node can hold several keys: when one hits its limit the next key takes over, and only when all keys are spent "
            "does the chain fall through to the next model. An optional egress pool gives each key its own exit IP. "
            "Ships as an npm CLI, a Docker image and a local web dashboard, with no telemetry."
        ),
        "repo": "https://github.com/colombefioren/COKEY",
        "demo_link": "https://cokey.vercel.app",
        "project_type": "NODE_EXPRESS",
        "code": {
            "review_score": 9.2,
            "summary": (
                "The most engineered project in the showcase: 36k lines of TypeScript with a Fastify proxy, a React "
                "dashboard, a CLI, encrypted credential storage and 24 test files. The routing core is careful: credentials "
                "are ordered by cooldown state, rotation cursor and in-flight load before each request."
            ),
            "architecture": (
                "src/core holds chains, credentials (cooldown, selector, masking), crypto and SQLite repositories; src/server "
                "exposes the OpenAI-compatible routes with streaming; src/web is the dashboard; src/cli the command line."
            ),
            "strengths": [
                "Credential selection skips disabled and cooling-down keys and balances in-flight load (src/core/credentials/selector.ts)",
                "Secrets are encrypted at rest with a keyring (src/core/crypto)",
                "Dedicated tests for router fallback, SSRF protection and quota parsing (tests/)",
                "Eight CI workflows including CodeQL, release gating and registry guards",
            ],
            "weaknesses": [
                "src/core/cokey.ts is a 1.5k-line orchestrator that would benefit from splitting",
                "Provider catalog files are large hand-maintained tables that will drift",
            ],
            "risks": [
                "Rotating many free keys and exit IPs may conflict with some providers' terms of service",
            ],
            "evidence": [
                {"file": "src/core/credentials/selector.ts", "note": "cooldown-aware, load-balanced key ordering"},
                {"file": "src/core/router/engine.ts", "note": "node fallback when every key of a node is exhausted"},
                {"file": "tests/router-fallback.test.ts", "note": "fallback behaviour covered by tests"},
                {"file": "tests/ssrf.test.ts", "note": "custom endpoints are guarded against SSRF"},
            ],
            "files_reviewed": [
                "src/core/credentials/selector.ts", "src/core/router/engine.ts", "src/core/cokey.ts",
                "src/core/crypto/secrets.ts", "src/server/openai", "tests/router-fallback.test.ts",
            ],
        },
        "market": {
            "profile": {
                "pitch": "One OpenAI-compatible endpoint that keeps working on free LLM tiers by rotating keys and falling back across providers.",
                "problem": "Free LLM tiers are generous in total but fragmented, rate limited per key and per IP, and they fail at random.",
                "solution": "A local gateway with key-first rotation, ordered model fallback and optional per-key egress IPs.",
                "category": "LLM gateways and routers",
                "target_users": ["Students and indie developers without an AI budget", "Hackathon teams and prototypers"],
            },
            "summary": (
                "LLM gateways are an active category: OpenRouter aggregates paid and free models [3], LiteLLM offers "
                "self-hosted fallbacks and key management [8][10], and several comparisons list alternatives [1][5]. "
                "COKEY's angle, maximizing free tiers with key-first rotation, is distinctive for budget-constrained developers."
            ),
            "audience": [
                {"name": "Students and indie hackers", "need": "use capable models without paying"},
                {"name": "Hackathon teams", "need": "a reliable endpoint that survives rate limits during a demo"},
                {"name": "Open-source tool authors", "need": "a free default backend for their users"},
            ],
            "problem_severity": "High for people on free tiers: limits like 20 requests per minute or 1,000 per day break tools quickly [12].",
            "market_size": "No direct market figure found for free-tier routing; the demand signal is the size of community lists of free LLM APIs [11].",
            "market_trend": "Comparisons of free LLM APIs and router alternatives are published regularly in 2026 [12][2].",
            "competitors": [
                {"name": "OpenRouter", "description": "Hosted router to many models, including some free ones", "differentiation": "COKEY is self-hosted, uses your own keys and focuses on free tiers", "source": 3},
                {"name": "LiteLLM", "description": "Open-source proxy with fallbacks, virtual keys and key rotation", "differentiation": "COKEY ships a curated free-provider catalog and per-key egress; LiteLLM is broader and enterprise-oriented", "source": 10},
                {"name": "Portkey", "description": "AI gateway with routing and observability", "differentiation": "COKEY is free, local and has no telemetry", "source": 1},
                {"name": "LLM Gateway", "description": "Gateway positioned against OpenRouter", "differentiation": "COKEY targets zero-cost usage rather than paid routing", "source": 4},
            ],
            "differentiation": "Free-tier maximization with key-first rotation and per-key IPs is a niche the big gateways do not target.",
            "business": {
                "business_model": "Open-source core with optional paid hosted version or sponsorship; monetizing free-tier arbitrage directly is risky.",
                "revenue_streams": ["GitHub sponsorships", "Hosted team edition", "Support for schools and bootcamps"],
                "go_to_market": ["Publish in free-LLM and developer communities", "Integrations guides for popular editors and agents"],
                "risks": [
                    {"risk": "Providers tighten free tiers or forbid rotation", "severity": "high", "mitigation": "Keep paid providers first-class in chains"},
                    {"risk": "Direct monetization conflicts with provider terms", "severity": "medium", "mitigation": "Monetize the tooling, not the free access"},
                ],
                "opportunities": ["Education market", "Agent frameworks needing cheap fallbacks"],
                "verdict": "Strong developer pull and a clear niche; the business model needs care around provider terms.",
            },
            "scores": {"market_potential": 7.6, "differentiation": 8.0, "viability": 6.6},
        },
        "product": {
            "summary": (
                "A thoughtful tool that turns a real pain point into a clean experience: CLI install, visual chain builder, "
                "live route graph and honest quota display. Distribution through npm and Docker Hub makes it easy to try."
            ),
            "scores": {"innovation": 8.4, "theme_fit": 8.6, "user_experience": 8.3},
            "rationales": {
                "innovation": "Key-first rotation plus per-key egress IPs is a genuinely new take on LLM routing.",
                "theme_fit": "A developer tool built around AI, the heart of the showcase themes.",
                "user_experience": "One-command install, dashboard with route visualization and translations; a lot of documentation to digest.",
            },
            "wow_factor": "A chain that keeps answering while keys die underneath it.",
            "suggestions": ["Split the core orchestrator", "Document provider terms-of-service considerations up front"],
            "claims": [
                {"claim": "Key-first rotation on 429, invalid key and provider 5xx", "status": "implemented", "file": "src/core/router/engine.ts", "note": "errors are classified; limited keys enter a Retry-After aware cooldown and the next key is tried"},
                {"claim": "Ordered node fallback across providers", "status": "implemented", "file": "src/core/router/engine.ts", "note": "falls through only after a node's keys are exhausted"},
                {"claim": "One OpenAI-compatible endpoint with streaming", "status": "implemented", "file": "src/server/openai", "note": "OpenAI routes and streaming helpers"},
                {"claim": "Automatic egress pool with one exit IP per key", "status": "implemented", "file": "src/core/providers/proxy-pool.ts", "note": "proxy pool with health checks, covered by tests/proxy.test.ts"},
                {"claim": "Encrypted local credential storage", "status": "implemented", "file": "src/core/crypto/secrets.ts", "note": "keyring-backed encryption"},
            ],
        },
        "criteria": {
            "Technical Execution": (9.1, "Deeply engineered routing core with encryption, SSRF guards, extensive tests and serious CI."),
            "Innovation": (8.4, "Free-tier maximization with key-first rotation is a fresh angle on LLM gateways."),
            "Market Potential": (7.5, "Clear developer demand and differentiation; monetization must respect provider terms."),
            "UX & Presentation": (8.3, "Easy install, visual chain builder and a detailed README."),
            "Completeness": (9.3, "Every claim is backed by code, including the egress pool with its own tests."),
        },
        "verdict": {
            "headline": "The strongest engineering in the showcase, solving a real developer pain.",
            "summary": (
                "COKEY pairs a distinctive idea with production-grade execution: careful credential selection, encryption, "
                "tests for failure paths and a published CLI and image. The main question is long-term viability as "
                "providers adjust their free tiers."
            ),
            "strengths": ["Robust, well-tested routing core", "Distinctive free-tier angle", "Published on npm and Docker Hub"],
            "improvements": ["Address provider terms explicitly", "Modularize the 1.5k-line core file"],
        },
    },
    # ------------------------------------------------------------------ KOTORI
    {
        "key": "kotori",
        "name": "KOTORI",
        "short": "A pastel paper studio that writes you a 400-word story and reads it aloud, word by word.",
        "long": (
            "Give Kotori one line and it writes a full story, typed onto the page one word at a time, then a voice reads it "
            "back while every word lights up in sync, like karaoke. Ten genres, eight moods, twelve voices across nine "
            "languages, a library of saved stories with recordings, and demo reels so it works without any API key."
        ),
        "repo": "https://github.com/colombefioren/KOTORI",
        "demo_link": "https://kotori-z3i4.onrender.com",
        "project_type": "OTHER",
        "code": {
            "review_score": 8.2,
            "summary": (
                "A clean Python package around a Gradio app, with core logic separated from UI and 17 test files. The "
                "word highlighting is a pragmatic design: instead of forced alignment, each word gets a duration weight "
                "from its length and punctuation that the client scales to the real audio length."
            ),
            "architecture": (
                "src/kotori/core holds story generation, prompts, speech, timing and the library; src/kotori/ui builds the "
                "studio, markup and callbacks; custom JS drives the teleprompter and highlighting."
            ),
            "strengths": [
                "Weight-based word timing avoids a second model while tracking TTS closely (src/kotori/core/timing.py)",
                "Demo reels make the app fully usable without credentials (src/kotori/core/demo.py)",
                "Tests cover prompts, timing, speech, accessibility and styles",
                "Docker, docker-compose and CI are in place",
            ],
            "weaknesses": [
                "Speech relies on gTTS, which limits voice quality and needs network access",
                "A lot of UI lives in hand-written markup and large CSS files",
            ],
            "risks": ["gTTS is an unofficial Google endpoint and can break or rate limit"],
            "evidence": [
                {"file": "src/kotori/core/timing.py", "note": "per-word duration weights from length and punctuation"},
                {"file": "src/kotori/core/speech.py", "note": "gTTS synthesis with language and accent presets"},
                {"file": "src/kotori/core/story.py", "note": "streamed 400-word story generation"},
                {"file": "tests/test_timing.py", "note": "timing behaviour under test"},
            ],
            "files_reviewed": [
                "src/kotori/core/timing.py", "src/kotori/core/speech.py", "src/kotori/core/story.py",
                "src/kotori/ui/studio.py", "src/kotori/assets/scripts/teleprompter.js",
            ],
        },
        "market": {
            "profile": {
                "pitch": "Personal short stories written and narrated on demand, with karaoke-style reading.",
                "problem": "Families and learners want fresh stories read aloud without recording or buying new books.",
                "solution": "A studio that writes a story from one line and narrates it with synced word highlighting.",
                "category": "AI story generators with narration",
                "target_users": ["Parents at bedtime", "Language learners who read along"],
            },
            "summary": (
                "AI stories with narration are a fast-growing, competitive space: Gemini Storybook produces illustrated, "
                "narrated books [4], and many bedtime apps compete on voices and personalization [6][8]. Kotori's "
                "karaoke-style reading and multilingual voices point to a language-learning angle."
            ),
            "audience": [
                {"name": "Parents", "need": "a new bedtime story every night"},
                {"name": "Language learners", "need": "read along with synced highlighting in nine languages"},
                {"name": "Teachers", "need": "quick read-aloud stories on a topic"},
            ],
            "problem_severity": "Moderate: parents value novelty and narration, with voice cloning raising expectations [8].",
            "market_size": "AI story generator tools are estimated at about USD 1.5 billion in 2025 with a 25% CAGR to 2033 [11].",
            "market_trend": "AI-generated storytelling reached USD 1.84 billion in 2024 according to one report [12].",
            "competitors": [
                {"name": "Gemini Storybook", "description": "Illustrated 10-page stories with read-aloud narration", "differentiation": "Kotori focuses on word-by-word highlighting and multilingual voices, without illustrations", "source": 4},
                {"name": "ReadKidz", "description": "AI children's book generator", "differentiation": "Kotori is about reading along, not publishing books", "source": 1},
                {"name": "Storytime AI", "description": "Mobile story generator app", "differentiation": "Kotori runs in the browser and works without an account", "source": 5},
            ],
            "differentiation": "Read-along highlighting across nine languages is a real hook for learners [8].",
            "business": {
                "business_model": "Subscription for families and schools with premium voices and a larger library.",
                "revenue_streams": ["Family plan", "Classroom licenses"],
                "go_to_market": ["Language-learning communities", "Teachers looking for read-aloud material"],
                "risks": [
                    {"risk": "Big tech ships similar features for free", "severity": "high", "mitigation": "Own the language-learning niche"},
                    {"risk": "Child safety of generated content", "severity": "medium", "mitigation": "Moderation and age presets"},
                ],
                "opportunities": ["Graded readers for language schools"],
                "verdict": "Charming product in a hot category; needs a sharp niche to survive big-tech competition.",
            },
            "scores": {"market_potential": 6.8, "differentiation": 6.0, "viability": 5.9},
        },
        "product": {
            "summary": (
                "Delightful and complete: the scrapbook interface is distinctive, the karaoke reading works, and demo reels "
                "let anyone try it immediately. A strong showcase of presentation."
            ),
            "scores": {"innovation": 7.5, "theme_fit": 7.2, "user_experience": 9.1},
            "rationales": {
                "innovation": "Story generators are common; synced read-along highlighting is less so.",
                "theme_fit": "An AI product with a creative, real-time reading experience.",
                "user_experience": "Memorable scrapbook design, works with no key, clear three-room layout.",
            },
            "wow_factor": "Every word lights up in time with the voice.",
            "suggestions": ["Offer higher-quality neural voices", "Add a learner mode with translations on tap"],
            "claims": [
                {"claim": "Writes a 400-word story from one line", "status": "implemented", "file": "src/kotori/core/story.py", "note": "prompted generation with streaming"},
                {"claim": "Word-by-word highlighting in time with the voice", "status": "implemented", "file": "src/kotori/core/timing.py", "note": "weights scaled to audio duration on the client"},
                {"claim": "Twelve voices across nine languages", "status": "implemented", "file": "src/kotori/core/speech.py", "note": "gTTS language and accent presets"},
                {"claim": "Works without an API key", "status": "implemented", "file": "src/kotori/core/demo.py", "note": "bundled demo reels"},
                {"claim": "Export stories as text or mp3", "status": "partial", "file": "src/kotori/ui/studio.py", "note": "recordings are kept as mp3 files per draft; no text export path was found in the reviewed files"},
            ],
        },
        "criteria": {
            "Technical Execution": (8.0, "Well-structured package with tests and a clever timing approach; limited by gTTS."),
            "Innovation": (7.5, "Read-along highlighting sets it apart from plain story generators."),
            "Market Potential": (6.4, "Growing market, but crowded and exposed to big-tech features."),
            "UX & Presentation": (9.1, "The most distinctive and polished interface in the showcase."),
            "Completeness": (8.6, "Nearly everything advertised works without setup; text export was not found."),
        },
        "verdict": {
            "headline": "The most delightful experience in the showcase, and it just works.",
            "summary": (
                "Kotori combines a memorable design with solid engineering and a no-key demo mode. Market potential is its "
                "weakest area: storytelling apps are crowded, so a focused niche like language learning would help."
            ),
            "strengths": ["Exceptional presentation", "Works instantly with demo reels", "Tested core logic"],
            "improvements": ["Pick a niche such as language learning", "Upgrade voice quality"],
        },
    },
    # ------------------------------------------------------------------ NUGGET
    {
        "key": "nugget--backend",
        "name": "NUGGET",
        "short": "Ask your docs, get the nugget: multilingual hybrid-search RAG with cited, streamed answers.",
        "long": (
            "Nugget indexes PDF, DOCX, HTML, Markdown, CSV and JSON with local multilingual embeddings, retrieves with "
            "dense vectors plus BM25 fused by reciprocal rank fusion, rewrites follow-up questions, and streams answers "
            "with [n] citations from any OpenAI-compatible model. Ask in Japanese about a French PDF and get the answer in Japanese."
        ),
        "repo": "https://github.com/colombefioren/NUGGET--BACKEND",
        "demo_link": None,
        "project_type": "FASTAPI",
        "code": {
            "review_score": 7.6,
            "summary": (
                "A compact FastAPI service (about 760 lines) that implements hybrid retrieval by hand instead of relying "
                "on a framework default: its own BM25 with accent folding and CJK bigrams, fused with vector results "
                "through RRF. Small, readable and focused."
            ),
            "architecture": (
                "app/main.py exposes ingest, query and streaming endpoints; app/retrieval.py does hybrid search; "
                "app/store.py wraps Chroma; app/loaders.py parses documents; app/llm.py calls the model."
            ),
            "strengths": [
                "Custom BM25 handles accents and CJK scripts, which generic tokenizers miss (app/retrieval.py)",
                "Reciprocal rank fusion merges keyword and vector rankings (app/retrieval.py)",
                "Local ONNX embeddings keep documents on the machine",
                "API and retrieval tests exist (tests/)",
            ],
            "weaknesses": [
                "No CI workflow and only six commits, so development history is thin",
                "The keyword index lives in process memory and is rebuilt per process",
            ],
            "risks": ["In-memory BM25 will not scale to large corpora or multiple workers"],
            "evidence": [
                {"file": "app/retrieval.py", "note": "BM25 with accent folding and CJK bigrams, fused with RRF"},
                {"file": "app/main.py", "note": "SSE streaming endpoint emitting sources, tokens and done"},
                {"file": "app/loaders.py", "note": "PDF, DOCX, HTML, Markdown, CSV and JSON loaders"},
                {"file": "tests/test_retrieval.py", "note": "retrieval tests"},
            ],
            "files_reviewed": ["app/retrieval.py", "app/main.py", "app/store.py", "app/loaders.py", "app/llm.py"],
        },
        "market": {
            "profile": {
                "pitch": "Private, multilingual document Q&A with grounded citations.",
                "problem": "Keyword search misses meaning and vector search misses exact terms, especially across languages.",
                "solution": "Hybrid retrieval with local embeddings and cited, streamed answers in the user's language.",
                "category": "Document chat and RAG tools",
                "target_users": ["Teams with multilingual documentation", "Privacy-conscious users"],
            },
            "summary": (
                "Document chat is saturated with open-source options such as AnythingLLM alternatives, kotaemon and "
                "Open WebUI [2][3], and hybrid BM25 plus vector retrieval is now common advice [7][10]. Nugget's edge "
                "is cross-lingual quality in a small, self-hostable service."
            ),
            "audience": [
                {"name": "Multilingual teams", "need": "ask in one language about documents in another"},
                {"name": "Privacy-sensitive users", "need": "embeddings computed locally"},
            ],
            "problem_severity": "Real for multilingual organizations; less so for single-language users.",
            "market_size": "AI enterprise search was valued at USD 8.6 billion in 2025, projected to USD 36.2 billion by 2034 [12].",
            "market_trend": "Hybrid search with RRF is becoming standard practice for RAG accuracy [8].",
            "competitors": [
                {"name": "kotaemon", "description": "Open-source RAG tool for chatting with documents", "differentiation": "Nugget is a lighter API with custom multilingual BM25", "source": 2},
                {"name": "AnythingLLM and alternatives", "description": "Desktop and self-hosted document chat suites", "differentiation": "Nugget focuses on retrieval quality rather than a full suite", "source": 3},
            ],
            "differentiation": "Cross-lingual hybrid retrieval that handles CJK and accents well.",
            "business": {
                "business_model": "Open-source API with paid hosting or support for multilingual teams.",
                "revenue_streams": ["Hosted plans", "Integration services"],
                "go_to_market": ["Target companies with multilingual documentation"],
                "risks": [{"risk": "Saturated category", "severity": "high", "mitigation": "Specialize in multilingual retrieval quality"}],
                "opportunities": ["Embedding it in support tools"],
                "verdict": "Technically sharp, commercially crowded.",
            },
            "scores": {"market_potential": 5.8, "differentiation": 5.6, "viability": 5.4},
        },
        "product": {
            "summary": (
                "A focused backend that delivers on its promises. As a submission on its own it lacks a user-facing demo, "
                "which the separate NUGGET--FRONTEND repository provides."
            ),
            "scores": {"innovation": 6.6, "theme_fit": 8.0, "user_experience": 5.8},
            "rationales": {
                "innovation": "Hybrid RAG is known; the multilingual tokenizer work is the novel detail.",
                "theme_fit": "An AI retrieval service, right on theme.",
                "user_experience": "Clean API and README, but no live demo linked to this submission.",
            },
            "wow_factor": "Cross-lingual answers with exact citations.",
            "suggestions": ["Link the frontend and a live demo", "Add CI and persist the keyword index"],
            "claims": [
                {"claim": "Hybrid retrieval with BM25 and vectors fused by RRF", "status": "implemented", "file": "app/retrieval.py", "note": "RRF_K and BM25 implemented in the module"},
                {"claim": "Cross-lingual questions and answers", "status": "implemented", "file": "app/embeddings.py", "note": "multilingual MiniLM embeddings"},
                {"claim": "Every claim carries an [n] citation", "status": "implemented", "file": "app/llm.py", "note": "prompt and sources formatting"},
                {"claim": "Re-uploaded files are deduplicated by content hash", "status": "implemented", "file": "app/store.py", "note": "hash check before indexing"},
            ],
        },
        "criteria": {
            "Technical Execution": (7.4, "Careful retrieval code with tests, but small scope, no CI and an in-memory keyword index."),
            "Innovation": (6.6, "Multilingual tokenization is a nice touch in a well-known pattern."),
            "Market Potential": (5.6, "Big market, saturated with document chat tools."),
            "UX & Presentation": (5.8, "Backend only, with no live demo for this submission."),
            "Completeness": (8.8, "Everything claimed is implemented."),
        },
        "verdict": {
            "headline": "Sharp retrieval engineering that needs a product around it.",
            "summary": (
                "Nugget does exactly what it says with thoughtful multilingual search. As a standalone submission it is "
                "small and has no demo, and the market for document chat is crowded."
            ),
            "strengths": ["Custom multilingual BM25 with RRF", "Every claim verified in code"],
            "improvements": ["Ship with the frontend and a live demo", "Add CI and scale the keyword index"],
        },
    },
    # ------------------------------------------------------------------ AIR QUALITY
    {
        "key": "air--quality---etl",
        "name": "Air Quality ETL",
        "short": "Hourly air-quality pipeline for six Madagascar cities, loaded into a PostgreSQL star schema.",
        "long": (
            "Collects AQI and eight pollutant metrics for six Malagasy cities from the OpenWeather Air Pollution API, "
            "cleans and validates the data, builds a star schema (dim_city, dim_date, fact_aqi) and loads it into "
            "PostgreSQL, orchestrated by Apache Airflow with an hourly DAG and a one-off backfill."
        ),
        "repo": "https://github.com/colombefioren/AIR--QUALITY---ETL",
        "demo_link": None,
        "project_type": "OTHER",
        "code": {
            "review_score": 7.7,
            "summary": (
                "A tidy data pipeline with clear extract, transform and load packages, explicit validation ranges for every "
                "pollutant and tests for each stage. Five contributors and focused fixes (UTC+3 timestamps, ISO 8601 parsing) "
                "show real iteration on data quality."
            ),
            "architecture": (
                "src/extract calls OpenWeather, src/transform/quality cleans, audits and validates, src/transform/transformer "
                "builds dimensions and facts, src/load writes CSV and PostgreSQL, dags/ orchestrates with Airflow."
            ),
            "strengths": [
                "Validation ranges for AQI and eight pollutants flag impossible values (src/transform/quality/data_validator.py)",
                "Star schema is documented and implemented (sql/, src/transform/transformer)",
                "Tests for extract, transform and load stages (tests/)",
                "Time-zone handling fixed explicitly for Antananarivo",
            ],
            "weaknesses": ["No dashboard or API on top of the warehouse", "Validation logs issues but does not quarantine bad rows"],
            "risks": ["Depends on a single upstream API and its free-tier limits"],
            "evidence": [
                {"file": "src/transform/quality/data_validator.py", "note": "range checks per pollutant"},
                {"file": "dags/air_quality_dag.py", "note": "hourly Airflow pipeline"},
                {"file": "src/load/postgres.py", "note": "load into the star schema"},
                {"file": "tests/test_transform/test_data_validator.py", "note": "validation tests"},
            ],
            "files_reviewed": [
                "src/transform/quality/data_validator.py", "src/extract/aqi_extractor.py",
                "src/load/postgres.py", "dags/air_quality_dag.py",
            ],
        },
        "market": {
            "profile": {
                "pitch": "A clean, queryable history of air quality across Madagascar's main cities.",
                "problem": "Local air-quality history for Malagasy cities is scattered across dashboards and hard to analyze.",
                "solution": "An automated pipeline that builds an analysis-ready warehouse every hour.",
                "category": "Open environmental data",
                "target_users": ["Researchers and journalists", "Public health and city planners"],
            },
            "summary": (
                "Real-time AQI for Antananarivo is already visible on consumer dashboards [1][4], and OpenAQ aggregates "
                "open data with a focus on low- and middle-income countries [11][12]. The pipeline's value is an "
                "analysis-ready local warehouse rather than a new consumer product."
            ),
            "audience": [
                {"name": "Researchers", "need": "hourly historical data in a relational model"},
                {"name": "Local authorities and NGOs", "need": "trends across the six largest cities"},
            ],
            "problem_severity": "Meaningful for public health analysis, but the audience is small and mostly non-paying.",
            "market_size": "No market figure applies directly; this is a public-good data project.",
            "market_trend": "Open air-quality data efforts are expanding in low- and middle-income countries [12].",
            "competitors": [
                {"name": "OpenAQ", "description": "Non-profit aggregating open air-quality data worldwide", "differentiation": "The ETL adds a local star schema and hourly history for six cities", "source": 11},
                {"name": "AQI.in", "description": "Real-time AQI dashboards including Antananarivo", "differentiation": "The ETL provides raw history for analysis, not a dashboard", "source": 1},
                {"name": "WAQI (aqicn)", "description": "World air quality index map", "differentiation": "The ETL owns its data pipeline and schema", "source": 4},
            ],
            "differentiation": "Local focus and an analysis-ready schema.",
            "business": {
                "business_model": "Grant-funded or institutional; could offer an API to researchers.",
                "revenue_streams": ["Research grants", "Institutional partnerships"],
                "go_to_market": ["Partner with Malagasy universities and health NGOs"],
                "risks": [{"risk": "Limited willingness to pay", "severity": "high", "mitigation": "Pursue grants and partnerships"}],
                "opportunities": ["Public dashboard and alerts built on the warehouse"],
                "verdict": "Valuable public-good infrastructure with little commercial upside.",
            },
            "scores": {"market_potential": 4.6, "differentiation": 5.2, "viability": 4.4},
        },
        "product": {
            "summary": (
                "A complete, well-tested pipeline that does what it describes. There is no user-facing surface, so "
                "presentation relies on the README, which is clear and detailed."
            ),
            "scores": {"innovation": 5.4, "theme_fit": 7.4, "user_experience": 4.8},
            "rationales": {
                "innovation": "A classic ETL applied to an underserved region.",
                "theme_fit": "Fits the open data theme well.",
                "user_experience": "No dashboard or demo; strong documentation.",
            },
            "wow_factor": "Hourly air quality for six Malagasy cities in a clean star schema.",
            "suggestions": ["Add a small public dashboard", "Quarantine invalid rows instead of only logging them"],
            "claims": [
                {"claim": "Collects AQI and eight pollutants for six cities", "status": "implemented", "file": "src/extract/aqi_extractor.py", "note": "OpenWeather extraction per city"},
                {"claim": "Cleans and validates the data", "status": "implemented", "file": "src/transform/quality/data_validator.py", "note": "pollutant ranges"},
                {"claim": "Star schema loaded into PostgreSQL", "status": "implemented", "file": "src/load/postgres.py", "note": "dim_city, dim_date and fact_aqi"},
                {"claim": "Hourly and backfill Airflow DAGs", "status": "implemented", "file": "dags/backfill_dag.py", "note": "backfill plus hourly pipeline"},
            ],
        },
        "criteria": {
            "Technical Execution": (7.6, "Clean stages, validation and tests; missing a serving layer."),
            "Innovation": (5.4, "Standard ETL patterns, valuable local focus."),
            "Market Potential": (4.6, "Public-good project with limited commercial potential."),
            "UX & Presentation": (4.8, "No interface or demo; documentation carries it."),
            "Completeness": (8.6, "Everything described is built and tested."),
        },
        "verdict": {
            "headline": "Solid, honest data engineering without a product face.",
            "summary": (
                "The pipeline is complete, tested and well documented, with thoughtful data-quality fixes. It scores lower "
                "on market and presentation because nothing is exposed to end users yet."
            ),
            "strengths": ["Validated, tested pipeline", "Clear star schema"],
            "improvements": ["Add a dashboard or API", "Quarantine invalid rows"],
        },
    },
    # ------------------------------------------------------------------ vercel/ai-chatbot
    {
        "key": "ai-chatbot",
        "name": "Chatbot (Vercel template)",
        "short": "Open-source Next.js AI chatbot template built with the AI SDK.",
        "long": (
            "A full-featured, hackable Next.js chatbot: App Router with server components, AI SDK with multiple model "
            "providers through AI Gateway, artifacts for documents, code and sheets, Auth.js, Postgres persistence and "
            "Playwright end-to-end tests. Included in the showcase as an external reference project."
        ),
        "repo": "https://github.com/vercel/ai-chatbot",
        "demo_link": "https://chatbot.ai-sdk.dev",
        "project_type": "NEXT_JS",
        "code": {
            "review_score": 8.9,
            "summary": (
                "Professional-grade code from a team of ten contributors: typed API routes, Drizzle queries, tool calls for "
                "documents and weather, and Playwright tests for chat, auth and model selection."
            ),
            "architecture": (
                "app/(chat) and app/(auth) route groups, lib/ai for models, prompts, providers and tools, lib/db for Drizzle "
                "queries, artifacts/ for document types, components/ for the chat UI."
            ),
            "strengths": [
                "AI tools are isolated and typed (lib/ai/tools)",
                "End-to-end tests for chat, auth and model selector (tests/e2e)",
                "Biome, Husky pre-commit and CI keep quality consistent",
            ],
            "weaknesses": ["Large UI components such as prompt-input.tsx exceed 1k lines"],
            "risks": ["Tightly coupled to Vercel services (AI Gateway, Blob, Neon) by default"],
            "evidence": [
                {"file": "lib/ai/tools/create-document.ts", "note": "typed tool implementation"},
                {"file": "app/(chat)/api/chat/route.ts", "note": "streaming chat route"},
                {"file": "tests/e2e/chat.test.ts", "note": "Playwright end-to-end tests"},
            ],
            "files_reviewed": ["app/(chat)/api/chat/route.ts", "lib/ai/providers.ts", "lib/ai/tools/create-document.ts", "lib/db/queries.ts"],
        },
        "market": {
            "profile": {
                "pitch": "A starter for building your own ChatGPT-style app on Next.js.",
                "problem": "Teams want a production-quality chat UI without building auth, persistence and streaming themselves.",
                "solution": "An open-source template with those pieces already integrated.",
                "category": "Chat UI templates and self-hosted chat apps",
                "target_users": ["Developers starting AI products"],
            },
            "summary": (
                "A crowded field of ChatGPT clones and self-hosted chat UIs exists, from LibreChat and Open WebUI to many "
                "Next.js clones [3][6][7]. This template is a reference implementation rather than a hackathon idea [2]."
            ),
            "audience": [{"name": "Developers", "need": "a production-ready starting point for chat apps"}],
            "problem_severity": "Solved many times over; value is quality and maintenance.",
            "market_size": "No specific figure; the category is best measured by adoption of templates and self-hosted UIs [10].",
            "market_trend": "Self-hosted chat interfaces keep multiplying in 2026 comparisons [7].",
            "competitors": [
                {"name": "LibreChat", "description": "Multi-provider open-source chat interface", "differentiation": "The template is code to fork, not an app to deploy", "source": 6},
                {"name": "Open WebUI", "description": "Self-hosted AI platform with knowledge bases", "differentiation": "The template is lighter and Next.js native", "source": 6},
            ],
            "differentiation": "Polish and first-party AI SDK integration.",
            "business": {
                "business_model": "Drives adoption of Vercel's platform rather than earning revenue itself.",
                "revenue_streams": ["Platform usage"],
                "go_to_market": ["Distributed through Vercel templates"],
                "risks": [{"risk": "Commoditized category", "severity": "medium", "mitigation": "Stay the reference implementation"}],
                "opportunities": [],
                "verdict": "Excellent reference, not a new venture.",
            },
            "scores": {"market_potential": 5.4, "differentiation": 4.6, "viability": 6.0},
        },
        "product": {
            "summary": (
                "Polished and complete, with a live demo. As a hackathon entry it would be judged as a template: the idea is "
                "not new and most of the history predates the event."
            ),
            "scores": {"innovation": 4.6, "theme_fit": 7.0, "user_experience": 8.9},
            "rationales": {
                "innovation": "A well-known category and a public template.",
                "theme_fit": "AI and developer tooling, on theme.",
                "user_experience": "Refined chat UI with artifacts and a live demo.",
            },
            "wow_factor": "Artifacts for documents, code and sheets beside the chat.",
            "suggestions": ["Build something new on top of the template"],
            "claims": [
                {"claim": "Multiple model providers through AI Gateway", "status": "implemented", "file": "lib/ai/providers.ts", "note": "provider routing"},
                {"claim": "Chat history persistence", "status": "implemented", "file": "lib/db/queries.ts", "note": "Drizzle queries"},
                {"claim": "Authentication", "status": "implemented", "file": "app/(auth)", "note": "Auth.js routes"},
            ],
        },
        "criteria": {
            "Technical Execution": (8.8, "Professional code and end-to-end tests from an experienced team."),
            "Innovation": (4.6, "A public template in a saturated category."),
            "Market Potential": (5.3, "Useful to developers, commercially commoditized."),
            "UX & Presentation": (8.9, "Refined interface with a live demo."),
            "Completeness": (9.0, "Everything described is implemented."),
        },
        "verdict": {
            "headline": "Excellent engineering, but a maintained template that predates the event.",
            "summary": (
                "This reference project shows how the jury treats pre-existing work: code quality scores high, yet the "
                "integrity check flags that most commits predate the hackathon, and originality is low."
            ),
            "strengths": ["Professional codebase and tests", "Polished live demo"],
            "improvements": ["Submit original work built during the event"],
        },
    },
]
