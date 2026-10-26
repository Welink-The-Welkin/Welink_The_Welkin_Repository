# Wanderer Voice Fine-tuning Design

## Goal and Limitation

Improve Chinese articulation, reduce distortion, and make the local character voice more similar to the user's four supplied recordings. This is a local GPT-SoVITS candidate experiment. A model may approximate the speaker for arbitrary new text but cannot guarantee a sample-identical “one-to-one” reproduction; only replaying an already-recorded exact line can do that.

## Current Evidence

- The user supplied four MP3s totaling about 37 minutes: the 6.1 voice collection and 6.2, 6.3, and 6.6 main-story recordings.
- The local GPT-SoVITS v2Pro workspace, CUDA runtime, existing e15 GPT checkpoint, and 137 annotated 32-kHz training utterances are present.
- The 6.1 collection is the clean target-speaker foundation. The main-story recordings can contain multiple characters and background score; they must be screened before they enter a one-speaker dataset.
- Current production weights and reference audio are configured locally. Those and source MP3s must remain unchanged until a candidate passes evaluation.

## Design

- Create a uniquely named experiment directory outside the application repository. Keep original source assets read-only and derive all temporary audio and checkpoints in that experiment directory.
- Use the existing 6.1 training corpus as a speaker anchor. Inspect the local GPT-SoVITS audio-preparation, Chinese ASR/VAD, vocal-separation, and speaker-verification tools. Process the three story recordings only as needed, then retain segments that have a correct Chinese transcript, no overlapping speaker/music damage, and a high target-speaker similarity. Review ambiguous clips and exclude them by default.
- Retain source filename/time offsets, transcript, sample rate/duration, speaker-verification score, and inclusion/exclusion reason in a local manifest. Keep a held-out set that is not used for training.
- Train a separate candidate GPT/SoVITS checkpoint with the existing v2Pro base/config, redirected manifest and output paths. Do not write to existing logs, weights, cache, or `.env` during preparation/training.
- Compare current and candidate models on identical held-out recorded speech and identical novel-text prompts, with the same reference audio and inference parameters. Record ASR CER/WER, durations, silence/clipping checks, and listening notes focused on phoneme clarity, distortion, and speaker similarity.
- Do not activate a candidate automatically. If it passes objective checks and human listening, configure the application to use the candidate without overwriting the original; include the checkpoint identity in the synthesis cache key to prevent stale audio reuse. If no candidate passes, retain the current model and report the measured reason.

## Safety and Data Handling

- Never copy raw source MP3s or generated dataset audio into Git or the release package.
- Never overwrite or delete the active GPT/SoVITS checkpoint, existing training logs, or original assets.
- If a required separation, ASR/VAD, or speaker verification model is unavailable or fails to distinguish the target speaker, stop before training on uncertain or mixed speakers.
- Do not add any external data sources; the training corpus is limited to the user-provided recordings and existing local 6.1 target-speaker corpus.

## Verification

- Inventory every audio input, confirm candidate output paths are separate, and validate manifest paths and transcripts before training.
- Evaluate against a held-out set using fixed parameters and fixed test prompts; compare ASR error and clipping to the current baseline.
- Listen to matched samples before switching active weights. Tests also verify selected weight paths are included in the voice cache fingerprint.
