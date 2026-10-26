# Wanderer Voice Fine-tuning Implementation Plan

> **For agentic workers:** Use this plan task by task with verification checkpoints. Never put raw audio or model weights in Git.

**Goal:** Build an isolated, speaker-screened GPT-SoVITS v2Pro candidate from the provided voice materials and compare its articulation/distortion to the current local voice.

**Architecture:** Keep source assets read-only and create all derived data, manifests, training outputs, and evaluation artifacts in a new uniquely named directory under the local GPT-SoVITS workspace. Use existing Chinese ASR/VAD, vocal separation, and SV tools to admit only target-speaker utterances. Train redirected v2Pro experiment outputs, then compare current and candidate models using fixed utterances/prompts; never auto-promote.

**Tech Stack:** GPT-SoVITS v2Pro, local CUDA/PyTorch, bundled FFmpeg, FunASR/VAD, UVR5, built-in Chinese speaker verifier, local HTTP inference API.

**Spec:** `docs/superpowers/specs/2026-10-26-wanderer-voice-finetuning-design.md`

## Global Constraints

- Do not copy or modify the four original MP3s or current training samples.
- Do not write training outputs into existing `logs/wanderer`, active `GPT_weights_v2Pro`, active `.env`, voice cache, or tracked application directories.
- Do not add mixed-speaker or uncertain story clips to a one-speaker manifest.
- Hold out at least 10% of accepted speech and evaluate against the current model.
- Do not auto-activate or overwrite a candidate; only report its isolated path pending listening verification.

---

### Task 1: Isolated input and tool inventory

**Files:** no tracked source file changes; create metadata only in a new candidate experiment directory outside the repository.

**Inputs:** the supplied 6.1 voice collection and P7-6.2, P8-6.3, P9-6.6 recordings.

- [ ] Verify every source file exists, record its absolute path, file size, codec, sample rate, channels, and duration with the bundled `ffprobe.exe`. Verify the configured training root and current active checkpoint identities without modifying `.env`.
- [ ] Create a collision-resistant experiment path under `<GPT_SOVITS_ROOT>\logs\wanderer-provided-<date>-<run-id>` only after confirming it does not exist; keep raw source audio out of that folder and store derived data under `candidate/`.
- [ ] Inspect the local model cache for FunASR ASR, VAD, punctuation, UVR5 HP5/HP2, and speaker verification checkpoint assets. If a required asset is absent, test whether the existing runtime can download it from its configured public model host without changing production checkpoints; if not, stop at the inventory report.
- [ ] Write a local `manifest.json` inventory containing source path, SHA-256, media metadata, tool/model availability, active GPT/SoVITS baseline paths, and candidate path. Verify every output path differs from each baseline path.

### Task 2: Prepare and speaker-screen supplemental clips

**Files:** derived only under `<experiment>/candidate/source`, `<experiment>/candidate/vocals`, `<experiment>/candidate/segments`, and `<experiment>/candidate/manifest.json`.

- [ ] Use bundled FFmpeg to extract audio to candidate-local WAVs, resampled to 32 kHz mono; never alter or replace source files.
- [ ] Run UVR5 vocal separation on the three story recordings using the available main-vocal model, preserving candidate-only stems. Compare a few source/stem excerpts to verify separation did not introduce obvious metallic/phase damage; omit a damaged stem instead of “repairing” it into training data.
- [ ] Run Chinese ASR with timestamps and VAD on each separated recording. Manually correct proposed transcripts against listened speech; reject overlapping speakers, music-only material, clipped phonemes, and utterances that cannot be confidently matched to the target character.
- [ ] Build target-speaker anchor embeddings from at least 20 clean existing 6.1 training WAVs; score each supplemental segment with the local SV model against the anchor centroid. Calibrate threshold from same-speaker and different-speaker clips in the existing 6.1 set; require the candidate above the 95th percentile of the different-speaker calibration distribution and manually review every included clip.
- [ ] Record source timestamps, corrected transcript, segment path, duration, ASR confidence, similarity score, and include/exclude reason in the manifest. Assert every included clip lasts 1–12 seconds, has a non-empty transcript, and is target-speaker reviewed.
- [ ] Keep a deterministic 10% held-out split by source clip, not adjacent chunks; verify no clip or overlapping source interval occurs in both training and held-out sets.
- [ ] If separation or SV cannot isolate the target voice at a defensible threshold, keep only the already curated 6.1 baseline and stop instead of adding uncertain story audio.

### Task 3: Train a candidate in a redirected experiment

**Files:** candidate-local `config.json`, manifests, logs, GPT checkpoints, SoVITS checkpoints, and semantic files; do not modify source logs or weights.

- [ ] Copy the existing v2Pro experiment configuration to the candidate directory and change only experiment/output paths and the training file list; preserve seed, model version, base weights, and other hyperparameters for an apples-to-apples comparison.
- [ ] Build/preprocess candidate clips using the vendor pipeline with experiment paths explicitly set. Before each training command, print and verify the resolved config paths point only to the unique candidate directory or read-only base models.
- [ ] Train the candidate GPT stage first; then train the SoVITS stage from the isolated candidate manifest with a deterministic seed. Keep each stage's logs/checkpoints in the candidate directory and stop if GPU/runtime errors or clipping regressions appear.
- [ ] Record source manifest hash, config hash, runtime/GPU details, commands, start/end time, and final checkpoint SHA-256 in the experiment report.

### Task 4: Evaluate current versus candidate voice

**Files:** fixed prompts, generated WAVs, and evaluation report under `<experiment>/evaluation/`.

- [ ] Select 20 held-out recorded target utterances plus 10 fixed novel Chinese prompts covering retroflex initials, sibilants, plosives, erhua, and longer clauses. Use the same reference clip and inference parameters for both models.
- [ ] Point two temporary local GPT-SoVITS configurations to the current and candidate checkpoints respectively; do not change the game `.env` or the server at port 9880.
- [ ] Generate matched audio for baseline and candidate, validate WAV format, non-empty/silent output, clipping peaks, and duration. Run the same local Chinese ASR on both and calculate CER/WER from the held-out transcripts.
- [ ] Record exact test prompts, checkpoint hashes, synthesis parameters, CER/WER, clipping/silence findings, and side-by-side human listening notes for consonant clarity, distortion, naturalness, and target voice similarity.
- [ ] Keep the candidate isolated and report its exact path. Do not promote it in this task; request listening confirmation before any `.env` change, service restart, or cache migration.

### Task 5: Integrated verification and handoff

- [ ] Run the chat-plan test suites and static checks; separately verify training manifest paths, held-out exclusion, checkpoint checksums, and absence of source MP3/model artifacts from `git status --short`.
- [ ] Summarize training/evaluation evidence, candidate path, remaining audition requirement, and whether story recordings contributed zero or a reviewed number of clean target-speaker clips.
