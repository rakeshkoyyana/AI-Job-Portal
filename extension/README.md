# JobPilot extension

1. Start the server: `python -m jobpilot api` (copy the printed token).
2. Chrome -> `chrome://extensions` -> enable Developer mode -> **Load unpacked** -> select this `extension/` folder.
3. Open the extension's Settings, paste the token, press **Save & test connection**.
4. LinkedIn: open a Jobs search with the **Easy Apply** filter, press Start. Indeed: open a search results page, press Start. Career sites: forms auto-fill when they appear, or use **Fill + submit this page** / **Fill only**.

Stay logged in on each site yourself. Daily caps and the minimum match probability come from `config.yaml` (`extension:`).

Caveat: selectors on LinkedIn/Indeed are brittle and were not verified against live sites. If a step stops working, check the console and adjust `content/linkedin.js` / `content/indeed.js`.

Tests: `npm install && npm test`.
