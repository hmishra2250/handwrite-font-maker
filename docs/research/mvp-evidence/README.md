# Saved-project MVP evidence

Local, actual HTTP/browser and font-tool evidence; not hosted-provider or Office acceptance.

The reproducible canaries are `scripts/smoke_project_browser.cjs` (guided sample → save → reload → edit metrics → rebuild → ZIP → mobile layout) and `scripts/smoke_template_projects.cjs` (unbuilt markerless/legacy sheet → autosave → reload → decoded preview → build enabled). They require the local Python backend on8011 and production Next preview on3011. No API mocks or paid inference are used in these canaries.

The guided sample is synthetic and tests workflow correctness, not photographic segmentation accuracy. Both model and nature-photo quality evidence remain in the separate segmentation/nature reports. An actual generated font is loaded in the browser; this does not establish Word/PowerPoint compatibility.

`report.json`, `font-package.zip`, and desktop/mobile screenshots are retained from the final guided canary. The ZIP contains the actual TTF/OTF, character map, and rights/installation notes. Project/job identifiers refer only to disposable local test data, not hosted customer records.

Final run: five initial uploads, no additional rebuild uploads, actual TTF2,552bytes / OTF2,700bytes / ZIP4,410bytes, mobile390px, no JavaScript errors. A's actual generated advance width is860 units after scale1.2 and spacing0.1em. `template-report.json` records the two unbuilt-sheet restore canaries; neither claims photographic extraction quality.

The final TTF was reopened in FontForge and A's advance was independently asserted to be860 units. The final read-only architecture recheck cleared the prior autosave/hydration P1s. The disposable PostgreSQL verification container was stopped and removed; the local app preview remains running. Hosted and Office gaps are unchanged.
