# Privacy and safe research

The current UI supports video upload to the configured local FastAPI service; uploaded files are persisted beneath `gui/runs` for analysis/results. This is **not** wholly browser-local processing. Use only data you are authorized to process, remove run artifacts after use, and do not upload identifiable health or facial information to an untrusted server. Live capture uses the backend host camera in the current local runtime, not automatically the user's browser camera. Camera capture should only be initiated knowingly; stop sessions when finished. No video should be collected from classmates or patients for this prototype. Further human research requires qualified supervision, consent, privacy/security controls and institutional oversight.

Anemia image analysis is not implemented and no image upload endpoint is provided. Do not submit medical images. Do not put personal data or datasets in Git.
