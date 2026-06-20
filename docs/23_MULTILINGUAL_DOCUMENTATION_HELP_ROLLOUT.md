# 23 — Multilingual Documentation, Help Content, and Rollout Playbook

## Objective

Document how Rudix handles multilingual UI, document ingestion, OCR, and chat
answers so admins, developers, and support teams can enable it safely and
troubleshoot issues quickly.

## Supported languages

### UI locales

Rudix currently ships the public and authenticated UI in:

- `en`
- `de`
- `es`
- `fr`

Locale selection is user-facing and persists in the profile settings flow.

### Document and answer languages

Rudix currently recognizes the same four ISO 639-1 codes for:

- document language detection
- answer language selection
- OCR language configuration
- language adherence evaluation

Supported OCR mappings are:

| ISO 639-1 | Tesseract |
| --- | --- |
| `en` | `eng` |
| `de` | `deu` |
| `es` | `spa` |
| `fr` | `fra` |

## Runtime behavior

### Document language detection

- Document text is analyzed during ingestion with a lightweight, deterministic
  detector.
- Detected language is stored on the document record as `language`.
- Confidence and source metadata are stored alongside the language code.
- Missing or low-signal text can leave the language unset.

### Answer language resolution

Chat requests accept an `answer_language` value.

- `auto` means "do not force a language instruction."
- `same_as_question` uses the detected question language when available.
- `en`, `de`, `es`, and `fr` force the answer language explicitly.
- The workspace fallback is `answer_language_workspace_default` and defaults to
  `en`.

If `FEATURE_ENABLE_LANGUAGE_AWARE_RAG=true`, the backend detects the question
language and records both the detected language and the resolved answer
language in chat debug metadata.

### OCR language choices

- PDF OCR uses the document language when available.
- Admins can override OCR languages per document with `PATCH /admin/documents/{document_id}/ocr-config`.
- Admins can override the detected document language with
  `PATCH /admin/documents/{document_id}/language`.
- OCR language lists are validated before use and are converted to Tesseract
  codes internally.

### Citation behavior

- Citations always point to the original source chunk and page metadata.
- Answer language does not rewrite source citations.
- If the model answers in a translated language, the citation text must still be
  source-faithful and chunk IDs must remain stable.
- Low-confidence OCR or language mismatches should surface as diagnostics, not
  silent data mutation.

## Admin rollout checklist

1. Confirm the target locale set is `en`, `de`, `es`, and `fr`.
2. Verify `FEATURE_ENABLE_LANGUAGE_AWARE_RAG=true` in the target environment.
3. Confirm `answer_language_workspace_default` is set to the preferred fallback.
4. Validate OCR language support on a PDF sample set for all four languages.
5. Verify document language override and OCR override endpoints are restricted
   to owner/admin roles.
6. Check that logs only include language codes, confidence, and request IDs.
7. Update support links and release notes before enabling the feature in
   production.
8. Run the manual QA checklist below before broad rollout.

## Support troubleshooting

### Wrong language in the UI

- Check the profile language setting.
- Confirm the locale cookie updated after save.
- Verify the localized messages bundle is present for `de`, `es`, and `fr`.
- If the wrong locale persists, clear cookies and reload the app.

### Wrong answer language

- Check the chat answer language selector.
- Confirm the question language was detected when `answer_language=auto`.
- Use `same_as_question` when the prompt should mirror the question language.
- If the workspace default is wrong, update `answer_language_workspace_default`.

### Low OCR quality

- Verify the document used the correct OCR language override.
- Check whether the PDF is scanned, rotated, or low resolution.
- Re-index after selecting the correct OCR language pack.
- Review page-level OCR warnings in document details.

### Missing translation or mixed-language answers

- Confirm the target locale exists in the UI bundle.
- Confirm the chat request used a supported answer language code.
- Check whether the answer is constrained by source language evidence.
- Review citations to see whether the answer was grounded in translated or
  source-language passages.

### Poor retrieval in multilingual documents

- Confirm the document language was detected correctly.
- Re-index with the correct language override when the detector is wrong.
- Ensure OCR produced text in the language expected by retrieval.
- Remember that retrieval quality still depends on chunk quality and source
  coverage; translation does not fix missing source text.

## Known limitations

- Only `en`, `de`, `es`, and `fr` are supported today.
- Language detection is heuristic-based and may be wrong on short samples.
- OCR language packs must be available in the runtime environment.
- Mixed-language documents may need manual language overrides.
- Answer language control changes generation language, not the source text.
- Citations remain anchored to the original source language and chunk IDs.

## Adding future languages

When adding another language:

1. Add the locale to the frontend message bundles and locale detection.
2. Add the language code to document and chat language validators.
3. Add OCR mappings and validate the OCR runtime package support.
4. Extend language detection heuristics and test fixtures.
5. Add evaluation cases for question language, answer language, and citation
   correctness.
6. Update support documentation and manual QA steps before rollout.

## User-facing help content

The help drawer should point users to the multilingual article from:

- Profile language settings
- Document details language and OCR sections
- Chat answer language controls

This keeps the guidance discoverable without exposing backend configuration.

## Internal QA checklist

- [ ] EN profile locale saves and reloads the app language.
- [ ] DE profile locale persists and the help article opens correctly.
- [ ] ES document language override saves and shows in document details.
- [ ] FR OCR override saves and document details display the new OCR language.
- [ ] Chat answer language set to `auto` follows question language.
- [ ] Chat answer language set to `de` returns German output.
- [ ] Chat answer language set to `es` returns Spanish output.
- [ ] Chat answer language set to `fr` returns French output.
- [ ] Citations still reference the original chunk/page metadata.
- [ ] Logs and audit entries contain no document text, prompts, or secrets.

