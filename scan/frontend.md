# Frontend Scan — Bakar (`frontend/`)

Date: 2026-10-31 · Scope: read-only scan of the assigned frontend files. All claims below were verified by reading the actual files; line numbers refer to the current working tree. Where something is inferred rather than read, it is marked as such.

---

## 1) What the UI does end-to-end

**One-paragraph answer (verified):** The frontend is a single-page voice-session UI. A server-rendered page loads app config, the client picks a token source (`/api/token` by default, a LiveKit Cloud "sandbox" endpoint if `NEXT_PUBLIC_CONN_DETAILS_ENDPOINT` is set), and renders a Welcome view until the LiveKit session connects. On connect it swaps to `AgentSessionView_01`: an audio/avatar tile with a visualizer, an optional chat transcript + text input, a control bar (mic / camera / screen-share / transcript / END CALL), and a custom Bakar "session recap" card. Pressing END CALL publishes an empty packet on the `bakar.end` data topic, waits 1.2 s for the agent to publish a recap on `bakar.recap`, then ends the session. There is no routing, no persistence, no storage — one page, two views.

### Session flow (verified, in order)

1. `app/page.tsx:6-10` — server component reads request headers, calls `getAppConfig(hdrs)` (`lib/utils.ts:24`, React `cache`d), renders `<App appConfig={...}/>`.
2. `components/app/app.tsx:31-38` — token source: sandbox endpoint (`lib/utils.ts:86-114`, sends `room_config.agents[{agent_name}]`) when `NEXT_PUBLIC_CONN_DETAILS_ENDPOINT` is set, otherwise `TokenSource.endpoint('/api/token')`. A code comment (app.tsx:36-37) explains that dispatch is configured **on the token** and that passing `agentName` to the session too would dispatch **a second agent**. `useSession(tokenSource)` owns the session.
3. `app.tsx:40-56` — `AgentSessionProvider` (`agents-ui/agent-session-provider.tsx:38-45`) wraps children in `SessionProvider` + `RoomAudioRenderer`. Side-effect component `AppSetup` runs `useDebugMode({enabled: NODE_ENV !== 'production'})` (`hooks/useDebug.ts:11-33`, sets livekit log level and exposes `window.__lk_room`) and `useAgentErrors()` (`hooks/useAgentErrors.tsx:29-72`, on `agent.state === 'failed'` shows a sonner toast with `failureReasons` and calls `session.end()`, de-duplicated once per session via `notifiedRef`, re-armed on disconnect). A global `StartAudioButton` (autoplay unblock; renders only when playback is blocked) and a themed `Toaster` finish the tree.
4. `components/app/view-controller.tsx:31-71` — `AnimatePresence mode="wait"` cross-fades (0.5 s) between `WelcomeView` (`!isConnected`) and `AgentSessionView_01` (`isConnected`). The start button calls `start` from `useSessionContext()`.
5. `components/app/welcome-view.tsx:45-84` — inline SVG equalizer mark, headline "Speak English like you already can.", subline "A friend who keeps you talking, catches the small things, and never grades you.", start button (`startButtonText` from config), and footer note: "Best with headphones. Pauses are fine — Bakar waits. Nothing is recorded or stored."
6. `agents-ui/blocks/agent-session-view-01/components/agent-session-block.tsx` — the session screen:
   - Transcript panel (top, `chatOpen` animated): `AgentChatTranscript` with `useSessionMessages(session)` messages (`agent-session-block.tsx:145-160`); auto-scrolls when the newest message is local (`:166-174`).
   - `TileLayout` (`tile-view.tsx:57-216`): if the agent publishes video it shows a `VideoTrack` avatar, otherwise an `AudioVisualizer` (`audio-visualizer.tsx:31-141`, switch over `bar | wave | grid | radial | aura`, all fed `useVoiceAssistant()` state + track). A second tile shows camera or screen-share when unmuted. Chat-open shrinks the visualizer to a small tile.
   - Bottom bar: shimmer pre-connect message "Take your time — say anything." while `messages.length === 0` (`:236-252`), then `AgentControlBar variant="livekit"` wired with `isChatOpen`, `isConnected`, `onDisconnect={handleDisconnect}`, `onIsChatOpenChange` (`:253-263`).
   - `<SessionRecap />` mounted last (`:295`).
7. Disconnect path (`agent-session-block.tsx:183-202`): publish `''` on topic `bakar.end` (reliable) → `await` 1200 ms → `session.end()`. This is the custom recap trigger (see §2).
8. `agents-ui/agent-control-bar.tsx:246-391` — mic/camera/screen toggles via `useInputControls` (`hooks/agents-ui/use-agent-control-bar.ts`), a chat textarea that sends through `useChat().send` (`:137-141`, Enter-without-Shift sends, `:110-115`), and `AgentDisconnectButton` labelled "END CALL"/"END". Controls auto-hide per publish permissions (`:315-323`).
9. `agents-ui/agent-chat-transcript.tsx:36-64` — each `ReceivedMessage` renders through the ai-elements `Conversation` (stick-to-bottom, scroll button) + `Message`/`MessageContent` + `MessageResponse` = `Streamdown` markdown (`ai-elements/message.tsx:264-272`); a pulsing `AgentChatIndicator` shows while `agentState === 'thinking'`.

Theming: `layout.tsx:48-113` sets `Public_Sans` + local `CommitMono`, injects `getStyles()` (accent CSS variables, see §4), renders fixed header (logo or text fallback + "Built on LiveKit" badge) and a hover-revealed `ThemeToggle` (dark/light/system, `theme-toggle.tsx:15-59`). OpenGraph card `app/opengraph-image.tsx:127-241` renders a 1200×628 PNG with wordmark + title, tolerating missing assets/fonts.

---

## 2) Recap data model and flow

### Data model — `lib/recap.ts`

- Wire constants: `RECAP_TOPIC = 'bakar.recap'` (`recap.ts:9`), `END_TOPIC = 'bakar.end'` (`recap.ts:10`), `RECAP_VERSION = 1` (`recap.ts:11`).
- `FocusArea = 'pronunciation' | 'grammar' | 'vocabulary' | 'fluency'` (`recap.ts:13-17`).
- `Recap = { version, wins: RecapWin[], focus: RecapFocus | null, drill: RecapDrill | null, durationSeconds: number }` (`recap.ts:19-35`); `RecapWin = {quote, why}`, `RecapFocus = {area, item, example}`, `RecapDrill = {sentence, hint}`.
- Bounds (`recap.ts:38-41`): `MAX_WINS = 3`, `MAX_TEXT = 400`, `MAX_DURATION_S = 4h`. `asText` trims + slices (`recap.ts:43-47`); `parseFocus` rejects unknown `area` and empty item/example (`recap.ts:49-63`); `parseWins` slices to 3 and drops entries without a quote (`recap.ts:73-87`).
- `parseRecap(raw)` (`recap.ts:89-121`): `JSON.parse` in try/catch → must be an object → `version !== 1` → `null`; `duration_s` clamped to `[0, 14400]` and rounded, non-numeric → 0. Header comment states the intent: "A data packet is untrusted input even when it comes from our own agent" (`recap.ts:2-4`).
- `formatDuration` → `m:ss` (`recap.ts:123-128`).

### Flow

1. **Trigger:** END CALL → `agent-session-block.tsx:193-197` publishes an empty string on `bakar.end`, reliable. Comment: "Ask the agent for the recap before the room empties: relying on the model to publish it on its own was advisory, not reliable."
2. **Agent side (backend, outside this scan):** the backend agent receives `bakar.end` and publishes a JSON recap on `bakar.recap`. The frontend does not verify the sender identity — it trusts any packet on that topic (mitigated by per-session rooms; see §3).
3. **Receive:** `hooks/useRecap.ts:13-25` — `useDataChannel(RECAP_TOPIC, handler)` decodes `Uint8Array` → UTF-8 → `parseRecap`; only a valid parse updates state. `dismiss` clears it. Comment: "Everything here is best-effort: if the packet never arrives, the session ends exactly as it did before this feature existed."
4. **Render:** `components/bakar/session-recap.tsx:15-110` — animated card (`role="status" aria-live="polite"`), header "{m:ss} of English", "You said" wins list, "Practise next" focus, "Say it once more" drill (monospace, dashed border), and an empty-state line when the card has no body (`hasBody`, `:20-21`). Renders `null` until a recap exists (`:23`).
5. **Timing race:** the recap must arrive within the fixed 1200 ms grace (`agent-session-block.tsx:198-199`, "Let the packet arrive and render before the session tears down") or `session.end()` (`:202`) destroys the data channel and the card never appears. There is no ack, retry, or extend-on-arrival mechanism. **State resets on unmount**: `SessionRecap` unmounts with the session view on disconnect, so a stale recap cannot leak into the next session.

### Verify scripts (contract tests, run manually with `node`)

- `scripts/verify-recap.mjs` — 9 checks: well-formed parse, unknown version → null, malformed JSON/"null"/"hello" → null, wins capped at 3, unknown focus area drops focus but keeps wins, empty session accepted (duration 0), 5000-char strings truncated to ≤400/≤160, non-numeric `duration_s` → 0, `formatDuration(0|65|512)` → `0:00|1:05|8:32`.
- `scripts/verify-fixes.mjs` — regression tests for two earlier bugs: (a) ids — 200 000 draws of `newRoomName()`/`newParticipantIdentity()` must be unique, prefix + RFC 4122 v4 shape (`verify-fixes.mjs:19-43`); (b) shader-uniform off-by-one — `isVectorType('3f', [1,0.5,0])` must be true etc. (`verify-fixes.mjs:47-77`). Both import the **real** `.ts` modules directly (`verify-fixes.mjs:6-7`, `verify-recap.mjs:5`).

---

## 3) Token endpoint analysis (`app/api/token/route.ts`) + security notes

### How tokens are minted (verified)

- `POST` only, no request body read. Reads `LIVEKIT_URL`, `LIVEKIT_API_KEY`, `LIVEKIT_API_SECRET`, `AGENT_NAME` (`route.ts:19-22`). Any missing var → HTTP 500 with `Server is missing <NAME>` and a server-side `console.error` (`route.ts:24-40`); comment explains this "fails loudly instead of minting a token that can never dispatch an agent".
- Fresh identifiers per request: `newRoomName()` / `newParticipantIdentity()` from `lib/ids.ts:17-31` — `bakar_room_<uuid4>` / `bakar_user_<uuid4>` via `crypto.randomUUID()`. The module docstring (`ids.ts:3-14`) records the two failure modes of the previous `Math.random()*10_000` scheme: identity collisions disconnect a live participant, and agent dispatch (carried by the token) only fires **on room creation**, so a reused room name silently lands the user in an agent-less room.
- Token (`route.ts:82-95`): `AccessToken` with `ttl: '15m'`; grant `{ room, roomJoin: true, canPublish: true, canPublishData: true, canSubscribe: true }` — no `roomCreate`, `roomList`, or admin grants. `at.roomConfig = RoomConfiguration.fromJson({agents:[{agentName}]})` (`route.ts:54`) ⇒ explicit agent dispatch baked into the token.
- Response: `{ serverUrl, roomName, participantName: 'user', participantToken }` with `Cache-Control: no-store` and `export const revalidate = 0` (`route.ts:14-16, 58-66`); token creation errors return a generic 500 "Could not create a session" with details only in logs (`route.ts:67-77`).
- Note on reading this file: the workspace reader masks the string literals `'LIVEKIT_API_KEY'` / `'LIVEKIT_API_SECRET'` (secret-name pattern). A raw read confirmed the ternary at `route.ts:25-31` is intact and correct — nothing is wrong in the file itself.

### Security assessment

| # | Observation | Evidence | Severity |
|---|---|---|---|
| S1 | **Unauthenticated, unthrottled token minting.** Anyone who can reach the deployment can POST and receive a valid join token that auto-dispatches the agent. Each minted session consumes backend LLM/TTS/STT budget (Murf, Deepgram, Gemini) — a scriptable cost-abuse vector. There is no CAPTCHA, rate limit, or origin check, and no `middleware.ts` exists in `frontend/` (verified by directory listing). | route.ts:18-66 | **High** for a public deployment (inherited starter design; locally moot) |
| S2 | **Blast radius is well contained.** The grant is scoped to one ephemeral room, 15-minute TTL, no room-listing/creation rights; UUIDv4 room names make joining someone else's session and duplicate-room dispatch practically impossible. The only "same room with a stranger" path is guessing a 122-bit UUID — negligible. | route.ts:85-92; ids.ts:3-31 | Mitigation (good) |
| S3 | **Secrets stay server-side.** Only `LIVEKIT_URL` (a public `wss://` URL by design) is returned to the client; key/secret are never echoed. Error bodies reveal *which* env var is missing but not its value. | route.ts:19-40, 58-66 | OK / trivial info disclosure |
| S4 | **Data-channel trust.** `useRecap` accepts any packet on `bakar.recap` without checking publisher identity. Combined with S1, a token-holder can only publish into their own ephemeral room, so cross-user spoofing is not practical, but the parser's defensive stance (bounded strings, version pinning) is what makes this acceptable. Note the rendering path is safe: recap strings are plain React text nodes, never HTML (`session-recap.tsx:47-107`). | useRecap.ts:13-22; recap.ts:2-4 | Low (design accepted + mitigated) |
| S5 | **Markdown rendering of chat.** Transcript text (agent *and* user messages) renders through `Streamdown` (`agent-chat-transcript.tsx:53`; `message.tsx:264-272`). Streamdown is built for untrusted LLM markdown; no `dangerouslySetInnerHTML` anywhere in the custom code. Residual risk limited to Streamdown itself. | message.tsx:264-272 | Low |
| S6 | **Remote accent-color injection is sanitized.** `getStyles` interpolates `accent`/`accentDark` (which can come from a remote sandbox config endpoint) into a `<style>` tag only after a strict hex regex (`lib/utils.ts:56-75`) — good XSS hygiene. | utils.ts:56-75 | Mitigation (good) |
| S7 | **`AGENT_NAME` is mandatory at runtime** (`route.ts:24` requires it, 500 otherwise) while `README.md` still describes it as "optional — for explicit agent dispatch" (Deployment section). `.env.example` documents it as required with an explanation of silent empty-room behavior. The README is stale. | route.ts:24; README.md (Deployment); .env.example:14-25 | Doc mismatch, medium confusion risk |
| S8 | `NEXT_PUBLIC_CONN_DETAILS_ENDPOINT` gates the sandbox token path (`app.tsx:31-33`, `lib/utils.ts:86`) but is **not listed in `.env.example`** (which only documents `NEXT_PUBLIC_APP_CONFIG_ENDPOINT` and `SANDBOX_ID`). | .env.example vs app.tsx:31 | Doc gap, low |

---

## 4) Custom-Bakar vs upstream-boilerplate split

`components.json:16-19` registers the two upstream registries (`@agents-ui` → `https://livekit.io/ui/r/{name}.json`, `@ai-elements` → `https://registry.ai-sdk.dev/{name}.json`), and `package.json`'s `shadcn:install` script re-installs exactly the vendored set — confirming which components are vendored boilerplate. Everything Bakar-specific is concentrated in a small set of files.

### Custom Bakar work (read, verified)

| File | What was customized |
|---|---|
| `app-config.ts:36-47,69` | Bakar branding: `companyName: 'Bakar'`, title "Bakar — speak English with confidence", tagline, `logo: '/bakar-mark.svg'`, orange accent `#C2410C` / `#FDBA74`, "Start talking", `agentName` from env |
| `app/api/token/route.ts` | Hardened: fail-loud on missing env, UUIDv4 room/identity from `lib/ids.ts`, required `AGENT_NAME`, explanatory comments (lines 41-43, 67-69, 71-72) |
| `lib/ids.ts` | Whole file — UUIDv4 ids replacing the upstream `Math.random()*10_000` scheme |
| `lib/recap.ts` | Whole file — recap schema, topics, defensive parser |
| `hooks/useRecap.ts` | Whole file — `bakar.recap` listener |
| `components/bakar/session-recap.tsx` | Whole file (only file in `components/bakar/`) — the recap card |
| `agent-session-block.tsx:183-202` | `handleDisconnect` — publishes `bakar.end`, 1200 ms grace — a surgical Bakar addition inside the vendored block; also custom default `preConnectMessage = 'Take your time — say anything.'` (`:117`) |
| `welcome-view.tsx:57-84` | Bakar copy ("Speak English like you already can.", privacy note); upstream kept the equalizer SVG |
| `layout.tsx:64-67` | `assetExists` fallback so a missing logo renders the company name instead of a broken image (assets now exist in `public/`: `bakar-mark.svg`, `bakar-mark-dark.svg`, `opengraph-image-bg.png`, both fonts — verified by listing) |
| `lib/utils.ts:56-75` | `safeCssColor` hex validation before style injection |
| `next.config.ts` | `eslint.ignoreDuringBuilds` with comment, `outputFileTracingIncludes` for `/` and `/opengraph-image` so serverless bundles keep `public/` |
| `opengraph-image.tsx:69-79` | `tryGetImageData` — a missing artwork/SVG no longer 500s the whole card |
| `hooks/useAgentErrors.tsx:40-45` | `notifiedRef` de-duplication of the failure toast/`end()` |
| `scripts/verify-fixes.mjs`, `scripts/verify-recap.mjs` | Plain-ESM regression/contract tests (no test runner wired into npm scripts) |
| `.env.example` | Rewritten with per-var rationale (why AGENT_NAME is required, dev/prod agent-name separation tip) |

### Upstream boilerplate (vendored, read/skimmed, not modified for Bakar)

- `components/agents-ui/*` — the LiveKit Agents UI registry set (see inventory in §5a).
- `components/ai-elements/*` — AI SDK "AI Elements": `conversation.tsx` (stick-to-bottom container + scroll button + empty state), `message.tsx` (bubbles, actions, message branching context, attachments, Streamdown response), `shimmer.tsx` (motion gradient text). Used only by `agent-chat-transcript.tsx` and `agent-session-block.tsx` (grep-verified import sites).
- `components/ui/*` — primitive shadcn components (not individually read; referenced by the above).
- `components/app/theme-provider.tsx`, `theme-toggle.tsx` — thin next-themes wrappers.
- `view-controller.tsx` — upstream view swap; Bakar touches only the props it forwards from config.
- `hooks/agents-ui/*` — registry hooks (see inventory).
- `lib/shadcn/utils.ts` — stock `cn()`.
- `taskfile.yaml` — LiveKit Sandbox template scaffolding ("Runs after this template is instantiated as a Sandbox").
- `README.md` — **largely upstream Murf-starter text**: the customization example still shows `companyName: 'Murf AI'`, `logo: '/murf-logo.svg'`, accent `#6366F1`; the Vercel deploy button clones `github.com/murf-ai/murf-livekit-starter`; `AGENT_NAME` described as optional (contradicting the token route). The project-structure and visualizer tables are accurate.
- `app-config.ts` schema/sandbox fields and `lib/utils.ts` `getAppConfig`/`getSandboxTokenSource` — upstream sandbox machinery, unmodified apart from the color guard.

---

## 5) Build / lint / test surface

### Scripts & toolchain (verified from `package.json`, configs)

- `dev` = `next dev --turbopack`; `build` = `next build`; `start`; `lint` = `next lint`; `format` / `format:check` = prettier (with import-sort + tailwind plugins); `shadcn:install` re-pulls the agents-ui/ai-elements registry set. `packageManager: pnpm@9.15.9` pinned.
- **No test runner.** The only executable tests are `node scripts/verify-fixes.mjs` and `node scripts/verify-recap.mjs` (documented in their headers). They import `.ts` modules directly, which requires Node ≥ 22.6 type-stripping (flag before 22.18; default from 22.18/23) — this was **not executed** during this scan (read-only task).
- `next.config.ts:3-8`: `eslint.ignoreDuringBuilds: true` — `next build` never lints; lint is manual-only. `outputFileTracingIncludes` includes `public/**` in the `/` and `/opengraph-image` serverless bundles.
- `tsconfig.json`: `strict: true`, `moduleResolution: bundler`, `@/*` → repo root paths; `scripts/*.mjs` sit outside the TS project by design (comment in `verify-fixes.mjs:4-5`).
- `eslint.config.mjs` — flat config via `FlatCompat` (`next/core-web-vitals`, `next/typescript`, import, prettier). A **legacy `.eslintrc.json` also exists** and is dead weight next to the flat config.
- Tailwind v4 through `@tailwindcss/postcss` (`postcss.config.mjs`); `styles/globals.css` defines the oklch token palette, `@custom-variant dark`, font variables, and `@source` for Streamdown.
- `taskfile.yaml` — `install`/`dev` conveniences + `post_create` sandbox message.

### Key dependencies (`package.json`)

`next 15.5.9`, `react/react-dom ^19`, `livekit-client ^2.17.2`, `livekit-server-sdk ^2.13.3` (token minting), `@livekit/components-react ^2.9.20`, `@livekit/protocol ^1.41.0` (RoomConfiguration), `motion`, `next-themes`, `sonner`, `lucide-react` + `@phosphor-icons/react`, `use-stick-to-bottom`, `streamdown` + `ai ^5` (transcript rendering types), `buffer-image-size` + `mime` (OG image), `@netlify/plugin-nextjs` (devDep).

**Flag:** `@rive-app/react-webgl2`, `@xyflow/react`, `tokenlens`, `media-chrome`, `embla-carousel-react`, `cmdk`, `shiki`, `nanoid`, `jose` are declared but have **no first-party import** anywhere under `app/`, `components/`, `hooks/`, `lib/` (grep across `**/*.{ts,tsx}`: zero matches). They presumably ship to satisfy registry component variants that were installed and later unused; they inflate install size and may be removable.

### Inventory (one-line roles)

**`components/agents-ui/` (rest beyond the four read in full):**
- `agent-audio-visualizer-aura.tsx` — WebGL-shader "aura" glow visualizer (derived from Unicorn Studio; carries a **Polyform Non-Resale License 1.0.0** header, lines 11-18) driven by agent audio.
- `agent-audio-visualizer-bar.tsx` — multiband-volume vertical bars, 5 size variants, clones a single child as the bar element.
- `agent-audio-visualizer-grid.tsx` — dot-grid visualizer with coordinate animator and density-based sizing.
- `agent-audio-visualizer-radial.tsx` — radial ring of bars; spins when agent state is `thinking`.
- `agent-audio-visualizer-wave.tsx` — GLSL oscilloscope wave (inline shader source) via `ReactShaderToy`.
- `agent-chat-indicator.tsx` — pulsing scale/opacity dot shown while the agent thinks.
- `agent-disconnect-button.tsx` — destructive leave button (`PhoneOffIcon`), calls session `end()` by default.
- `agent-track-control.tsx` — track toggle + media-device `Select` dropdown composite for mic/camera.
- `agent-track-toggle.tsx` — mic/camera/screen toggle button with icon state and default/outline variants.
- `react-shader-toy.tsx` — ~950-line minimal WebGL fragment-shader runner exposing Shadertoy-style uniforms (`iTime`, `iResolution`, …); uniform predicates factored into `lib/shader-uniforms.ts` for testability.
- `start-audio-button.tsx` — autoplay-unblock button; renders only when browser blocks playback.
- `blocks/agent-session-view-01/index.ts` — re-exports `agent-session-block` (the block's other files, `audio-visualizer.tsx`/`tile-view.tsx`, are internal).

**`hooks/` (rest):**
- `hooks/agents-ui/use-agent-control-bar.ts` — input controls: track toggles, device switching, publish permissions, persisted user choices.
- `hooks/agents-ui/use-agent-audio-visualizer-{aura,bar,grid,radial,wave}.ts` — per-visualizer motion/uniform animators.
- `hooks/useAgentErrors.tsx` — failure toast + session end (read in full, §1).
- `hooks/useDebug.ts` — dev log level + `window.__lk_room` handle.
- `hooks/useRecap.ts` — recap listener (§2).

**`lib/`:** `recap.ts` (§2), `ids.ts` (§3), `shader-uniforms.ts` (GLSL uniform type predicates, unit-tested), `utils.ts` (app-config fetch/merge, style injection, sandbox token source), `shadcn/utils.ts` (`cn`).

**Config:** covered in §5. `frontend/.env.example` lists `LIVEKIT_URL/KEY/SECRET`, `AGENT_NAME` (required), optional `NEXT_PUBLIC_APP_CONFIG_ENDPOINT`, `SANDBOX_ID`.

---

## 6) Issues found (file:line evidence)

Ordered by importance. "Verified" = read directly in this scan.

1. **Unauthenticated, unthrottled token minting with agent dispatch** — `app/api/token/route.ts:18-66`. Any reachable client can mint a 15-min participant token that auto-dispatches the backend agent; scriptable abuse burns Murf/Deepgram/Gemini budget. No rate limiting, CAPTCHA, or middleware exists. Inherited starter behavior; matters only for public deployments. (Verified)
2. **Recap delivery race** — `agent-session-block.tsx:193-202`. Fixed `setTimeout(1200)` grace between `bakar.end` publish and `session.end()`; a recap that takes longer (LLM latency) is silently lost, and the card renders nothing (by design, `session-recap.tsx:11-13`). No ack/extend mechanism. (Verified)
3. **`AGENT_NAME` requirement documented inconsistently** — required at `route.ts:24` (500 without it) and in `.env.example:14-25`; README Deployment section still says "AGENT_NAME (optional — for explicit agent dispatch)". A user following the README gets a hard 500 on `/api/token`. (Verified)
4. **`NEXT_PUBLIC_CONN_DETAILS_ENDPOINT` used but undocumented** — consumed at `app.tsx:31-33` / `lib/utils.ts:86` to switch to the LiveKit sandbox token path, absent from `.env.example`. (Verified)
5. **Lint does not gate builds + duplicate ESLint configs** — `next.config.ts:3-8` (`ignoreDuringBuilds: true`) means `pnpm build` passes regardless of lint; both `eslint.config.mjs` (flat) and `.eslintrc.json` (legacy) exist, so which one governs `pnpm lint` is ambiguous tooling state. (Verified)
6. **README drift to upstream Murf starter** — customization example shows `companyName: 'Murf AI'`, `logo: '/murf-logo.svg'`, `#6366F1`; deploy button clones `murf-ai/murf-livekit-starter` (README, Customization/Deployment sections). Harmless but misleading for new contributors. (Verified)
7. **Declared-but-unimported heavyweight dependencies** — `@rive-app/react-webgl2`, `@xyflow/react`, `tokenlens`, `media-chrome`, `embla-carousel-react`, `cmdk`, `shiki`, `nanoid`, `jose` in `package.json` with zero first-party imports (grep across all ts/tsx under app/components/hooks/lib). Install-size/bundle-surface cost; removal candidate after a build check. (Verified absence of imports; *inference* that they are safe to remove not tested)
8. **Third-party license note on the aura visualizer** — `agent-audio-visualizer-aura.tsx:11-18` carries a Polyform Non-Resale License 1.0.0 header ("Originally developed for Unicorn Studio"). Vendored via the LiveKit registry; worth legal awareness before commercial resale of this codebase. (Verified header text; license implications = inference)
9. **Missing-env name disclosure** — `route.ts:37` returns `Server is missing LIVEKIT_API_SECRET` etc. to anonymous callers; reveals server configuration shape only. Low. (Verified)
10. **`formatDuration` minutes are unbounded** — `lib/recap.ts:123-128` renders 4 h as `240:00` (parse caps duration at 4 h, `recap.ts:17`). Cosmetic. (Verified)
11. **Privacy claim needs backend cross-check** — `welcome-view.tsx:82` promises "Nothing is recorded or stored"; the frontend indeed has no recording/persistence code paths (verified), but the claim is only fully provable against the backend (out of this scan's scope).
12. **Minor:** transcript timestamp `title` uses `timeStyle: 'full'` incl. timezone (`agent-chat-transcript.tsx:55`) and reads `navigator?.language` during render — client-only component so no SSR hazard today. (Verified)

**Not issues (checked and cleared):** the token route's `missing` ternary is intact on disk (the file reader masks the literals `'LIVEKIT_API_KEY'`/`'LIVEKIT_API_SECRET'`; raw read confirmed `route.ts:25-31`); `getStyles` hex-sanitizes remote accent colors before injection; recap strings render as plain text, never HTML; recap state cannot leak across sessions (component unmounts on disconnect).

---

## 7) Not covered / suggested follow-up

- `components/ui/*` primitives and `hooks/agents-ui` hook bodies were only skimmed (inventory level, per task).
- Backend counterpart of the recap protocol (`bakar.recap`/`bakar.end` publishers) lives outside this scan; verifying sender-identity checks and recap generation latency there is the highest-value follow-up to issue #2.
- Running `node scripts/verify-*.mjs`, `pnpm lint`, and `pnpm build` was out of scope (read-only); the scripts' Node version requirement (≥22.6 for `.ts` imports) should be validated on the target machine.
