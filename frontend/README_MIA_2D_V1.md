# mIA 2D V1

## Files
- `mia-2d.html`: new 2D world page.
- `mia-2d.css`: mIA premium styling + all result renderers from the supplied `mia.html`.
- `mia-2d.js`: conversational client, rich result rendering, shared 2D/3D session and ElevenLabs voice client.
- `mia-elevenlabs-backend-patch.py`: Flask endpoint for the custom ElevenLabs voice.

## Put in the Vite frontend
Copy:
- `mia-2d.html` -> `frontend/mia-2d.html`
- `mia-2d.css` -> `frontend/mia-2d.css`
- `mia-2d.js` -> `frontend/mia-2d.js`

Then with Vite running:
- 2D: http://localhost:5173/mia-2d.html
- 3D: http://localhost:5173/

The 2D/3D control already points the 3D option to `/`.

## Backend voice
The browser NEVER receives `MIA_VOICE_ELEVEN_LABS_API_KEY`.
Add the contents of `mia-elevenlabs-backend-patch.py` to `avatar_backend_mia.py` after the v10.38 voice helpers.

You also need the ElevenLabs Voice ID, in:
`MIA_VOICE_ELEVEN_LABS_VOICE_ID`

Example environment variable:
`MIA_VOICE_ELEVEN_LABS_VOICE_ID=xxxxxxxxxxxxxxxxxxxx`

Your existing constant remains:
`MIA_VOICE_ELEVEN_LABS_API_KEY`

Restart Flask after adding the route.

## Development API defaults
When the page is opened on localhost:
- backend: http://127.0.0.1:5001
- LLM gateway: http://127.0.0.1:5002

In production, same-origin is used by default.
You can override before loading `mia-2d.js` with:
`window.MIA_BACKEND_BASE` and `window.MIA_GATEWAY_BASE`.

## Shared world session
Context is stored in localStorage key:
`mia.shared.session.v1`

The 3D world can read this same key when we update it, so changing worlds will preserve the conversation context.
