# Frontend Smoke Check

This check validates the public demo boundary without calling the model or writing an analysis audit record.

Start the API in public demo mode, then run:

```powershell
$env:VITE_BASE_URL = "http://127.0.0.1:8000/"
npm run smoke
```

The check verifies that the homepage serves a bundle containing the guided demo paths, the public session does not expose Trace visibility, and the demo overview has enough records and channel variation for the recruiting flow.
