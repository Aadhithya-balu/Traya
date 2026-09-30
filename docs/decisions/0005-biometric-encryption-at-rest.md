[../README.md](../README.md) | [Decisions](README.md)

# ADR 0005: Biometric embeddings are encrypted at rest and never returned

- **Status:** Accepted
- **Date:** 2026-08-15
- **Affects:** `app/security/crypto.py`, `app/models/entities.py` (`BiometricEmbedding`), `app/repositories/recognition.py`

## Context

A biometric embedding is a stable, replayable identifier. Unlike a password, it
cannot be rotated on breach and it does not expire - a leaked template is a
permanent compromise of the biometric. It is also a special category of personal
data under most privacy regimes, including India's DPDP Act.

## Decision

1. Embeddings are stored as Fernet-encrypted blobs in
   `biometric_embeddings.embedding_blob`. The Fernet key derives from
   `settings.encryption_key`, which is a distinct setting from `SECRET_KEY` so
   the two can be rotated independently.
2. **No endpoint ever returns an embedding.** `BiometricStatusOut` exposes only
   `status`, `enrolled_at`, `num_samples` and `algo_version`. There is no
   "export my biometrics" path, by design.
3. Re-enrollment **replaces** rather than appends. `ProfileRepository.replace_embeddings`
   deletes the old rows before inserting new ones, so a previous template cannot
   be resurrected.
4. Decryption is per-blob fault-tolerant. `RecognitionRepository.enrolled_profiles`
   skips any blob that fails to decrypt instead of aborting the whole match, so
   one corrupt or undecryptable row cannot take down identification for everyone.
5. `algo_version` is stored per embedding and on the profile, so a future
   algorithm change can be detected and re-enrollment forced.

## Consequences

**Good.** A database dump does not yield usable biometric templates. The ability
to silently skip an undecryptable profile is what allows the key to be rotated
without downtime.

**Costs, stated plainly.**

- **Rotating `SECRET_KEY` or `ENCRYPTION_KEY` makes every existing embedding
  permanently undecryptable.** Those profiles degrade to "not enrolled" and their
  users must re-enroll. There is no re-encryption migration. Treat the encryption
  key as permanent, or plan a re-enrollment campaign before rotating it.
- Encryption costs a symmetric decrypt per profile on every identification. At
  demo scale this is irrelevant; at city scale the match tier should cache
  decrypted templates with an explicit TTL rather than decrypting per request.
- Because the current engine is a simulation (ADR 0001), the encrypted blobs
  protect a feature vector that carries no real biometric information. The
  control is correct and will remain correct when a real embedder lands; today it
  protects nothing sensitive.
