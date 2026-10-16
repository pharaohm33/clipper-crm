# Handoff: Meta ads video maker + Dia voice

Repos: ~/clipper-crm (CRM + tools/, GitHub pharaohm33/cold-email-outreach-crm), ~/instagram-video-generator (Kokoro server, clipper app).
Full chat transcript is NOT in git (large, holds lead data): copy dia_handoff.zip over by hand if you want it.

## State (2026-10-16)
- Committed + pushed: 3a9acc4 (banner link locked to https://portal.aiadsoptimization.com/signup, voice 1.25x, silence trimmed, tighter captions, talking circle bubble with voice-reactive rings, photo in tools/assets/narrator.jpg).
- Committed in the handoff commit (after 3a9acc4): tools/ad_video.py link_start change (banner appears only at "If that sounds worth a look", after the pricing lines, no 20 s minimum); tools/local_runner.py fix (each video's share link was being passed to the next video as its banner link = the Drive-link bug), .gitignore entry tools/.dia_venv/, tools/dia_test.py.
- Pull on the new machine: git pull. The 3 videos (L3 Kennedy Blue, L5 Flip Aquatics, M3 Staple NYC) in tools/ad_videos/ are OLD; remake after choosing the voice. Restart helper after any tools/*.py change: kill $(lsof -ti :8765); python3 tools/local_runner.py
- Remake request: POST localhost:8765/ads/video (Origin http://localhost:8000) items [{id,company,email,first,business}], voice "kokoro:af_heart", host "loom".

## Dia (nari-labs/dia, 1.6B)
- Wanted as the new voice. Did NOT run on the 8 GB M1 (swap thrash, no output in 19 min). Needs ~4.4 GB VRAM/RAM free; GPU (CUDA) tested by the authors; try MPS on a 16 GB+ Apple Silicon or CUDA machine.
- tools/dia_test.py is the feasibility script (model nari-labs/Dia-1.6B-0626, float16, seed 7). On CUDA change device to torch.device("cuda").
- Setup: uv venv --python 3.11 .dia_venv; uv pip install "git+https://github.com/nari-labs/dia.git" soundfile
- Text format: start with [S1], alternate [S1]/[S2], end with the other speaker's tag; for a stable voice give a 5-10 s reference clip + its transcript first (see example/voice_clone.py), otherwise the voice changes every run.
- To plug in: add an engine "dia" in tools/ad_video.py speak() that returns (seconds, [(start,end,word)], voice_used) like _speak_kokoro, then run it through _speed_up if wanted (it handles tempo and word timings).
- Word timings: Dia gives no word boundaries; use _spread per sentence (as Kokoro does), generating one sentence at a time.

## Other open items
- Leads need Loom links before drafts can be saved; first Loom upload requires Connect Loom in the CRM.
- Discard first-email drafts for Negative Underwear and Cabeau (already emailed from Gmail) if you agree.
