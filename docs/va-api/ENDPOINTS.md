# SAS Viya API Endpoint Inventory

Generated from the OpenAPI specs in this directory:
`visualAnalytics-v8-openapi.yml`, `reports-v7-openapi.yml`, `reportTransforms-v3-openapi.yml`, `insights-v3-openapi.yml`.
Base paths on a Viya deployment: `/visualAnalytics`, `/reports`, `/reportTransforms`, `/insights`.

---

## Visual Analytics API (v8) — `/visualAnalytics`

| METHOD | PATH | operationId | summary |
|---|---|---|---|
| GET | / | root | Get a list of top-level links |
| GET | /reports/{reportId}/pdf | getExportedReportPdf | Export a PDF of a report |
| GET | /reports/{reportId}/svg | getExportedReportImageSVG | Export an SVG image of report or report object |
| GET | /reports/{reportId}/png | getExportedReportImagePNG | Export a PNG image of a report or report object |
| GET | /reports/{reportId}/package | getExportedReportPackage | Export a report package |
| GET | /reports/{reportId}/csv | getExportedReportCSV | Export data for one object in a report as comma-separated values |
| GET | /reports/{reportId}/tsv | getExportedReportTSV | Export data for one object in a report as tab-separated values |
| GET | /reports/{reportId}/xlsx | getExportedReportWorksheet | Export data for one object in a report as an XLSX file |
| GET | /reports/{reportId}/summary | getReportSummary | Export a report summary |
| POST | /reports/{reportId}/exportPackage | createExportPackageJob | Create and run an action to export a report as a package file |
| POST | /reports/{reportId}/exportPdf | createExportPdfJob | Create and run an action to export a report as a PDF file |
| POST | /reports/{reportId}/exportImage | createExportImageJob | Create and run an action to export an image file |
| POST | /reports/{reportId}/exportData | createExportDataJob | Create and run an action to export a data file |
| POST | /reports | createReport | Create a report while applying the specified operation(s) |
| PUT | /reports/{reportId} | updateReport | Update a report while applying the specified operation(s) |
| PUT | /reports/{reportId}/copy | updateReportCopy | Create a copy of a report |
| DELETE | /reports/{reportId} | deleteReport | Delete a report |
| GET | /jobs/{jobId} | getJobStatus | Get the job with its status and link to results |
| DELETE | /jobs/{jobId} | deleteJobStatus | Delete the job with its status and link to results |

Direct-export GET response media types: pdf → `application/pdf`; svg → `image/svg+xml`; png → `image/png`; package → `application/zip`; csv → `text/csv`; tsv → `text/tsv`; xlsx → `application/vnd.openxmlformats-officedocument.spreadsheetml.sheet`; summary → `text/plain`.

### Key request shapes

**POST /reports/{reportId}/exportData** — media `application/vnd.sas.visual.analytics.report.export.data.request+json` (or `application/json`):
- `format` (string, required; enum: `csv`, `tsv`, `xlsx`; default `xlsx`)
- `reportObject` (string, required)
- `resultFolder` (string), `resultFilename` (string), `nameConflict` (string; enum: `replace`, `rename`)
- `timeout` (integer), `wait` (integer)
- `options` (object): `startRow` (int, default 0), `endRow` (int, default -1), `columns` (array), `formattedData` (bool, default true), `detailedData` (bool, default false)
- `version` (integer, required)

**POST /reports/{reportId}/exportPdf** — media `application/vnd.sas.visual.analytics.report.export.pdf.request+json`:
- `resultFolder`, `resultFilename`, `nameConflict` (enum: `replace`, `rename`)
- `reportObjects` (array of string), `wait` (int), `timeout` (int)
- `options` (object, required): `orientation` (enum: `landscape`, `portrait`; default `landscape`), `paperSize` (enum: `letter`, `legal`, `A3`, `A4`, `A5`, `B4`, `B5`, `ledger`; default `letter`), `margin` (default `.25in`), `includeTableOfContents` (default false), `showPageNumbers` (default true), `showEmptyRowsAndColumns` (default false), `includeAppendix` (default true), `includeComments` (default false), `includeDetailsTables` (default false), `expandClippedContent` (default false), `includeCoverPage` (default true), `coverPageText` (default "")
- `version` (integer, required)

**POST /reports/{reportId}/exportPackage** — media `application/vnd.sas.visual.analytics.report.export.package.request+json`:
- `resultFolder`, `resultFilename`, `nameConflict` (enum: `replace`, `rename`), `reportObjects` (array of string), `timeout`, `wait`, `version` (required)

**POST /reports/{reportId}/exportImage** — media `application/vnd.sas.visual.analytics.report.export.image.request+json`:
- `resultFolder`, `resultFilename`, `nameConflict` (enum: `replace`, `rename`), `reportObject` (string)
- `image` (object, required): `format` (required; enum: `svg`, `png`), `size` (string, required — e.g. "600px,450px")
- `timeout`, `wait`, `version` (required)

**GET /reports/{reportId}/svg and /png** — query params: `reportObject` (optional; omit to render whole report), `size` (required), `wait` (default 30).
**GET /reports/{reportId}/pdf** — query params mirror the exportPdf options: `reportObjects`, `orientation` (`landscape`/`portrait`), `paperSize` (`letter`/`legal`/`A3`/`A4`/`A5`/`B4`/`B5`/`ledger`), `margin`, `showPageNumbers`, `showEmptyRowsAndColumns`, `includeTableOfContents`, `includeAppendix`, `includeComments`, `includeDetailsTables`, `expandClippedContent`, `includeCoverPage`, `coverPageText`.
**GET /reports/{reportId}/csv|tsv|xlsx** — query param `reportObject` (required).

**Report editing / operations request** — used by `POST /reports`, `PUT /reports/{reportId}`, and `PUT /reports/{reportId}/copy`; media `application/vnd.sas.report.operations.request+json`:
- `id` (string), `version` (integer)
- `resultFolder` (string), `resultReportName` (string), `resultNameConflict` (enum: `abort`, `rename`, `replace`)
- `operations` (array). Each operation = `operationId` (string), `includeObjectInResponse` (bool), plus exactly one of:
  - `addData`: `cas` (required: `server`, `library`, `table` required; `locale`), `uniqueRowId`, `dataItems[]` (`dataItem` required, `properties`)
  - `updateData`: `data` (required: `name`, `cas`), `uniqueRowId`, `dataItems[]`
  - `changeData`: `originalData` (required), `replacementData` (required), `forceReplace` (bool), `replacementLabel`, `replacementDataItems[]` (`replacementColumn` required, `originalColumn`, `originalName`)
  - `applyDataView`: `dataItemConflictResolution` (enum: `abort`, `createDuplicate`, `replaceExisting`, `keepExisting`, `dataMapping`), `targetData` (required), `dataView` (required: `uri`, `name`), `dataMapping`
  - `addPage`: `pageName`, `pagePosition`
  - `addObject`: `object` (oneOf ~60 `add<ChartType>Request` schemas — barChart, listTable, crosstab, keyValue, timeSeriesPlot, geo*, text, image, dataDrivenContent, controls, analytics objects, etc.), `reportObject`, `placement` (oneOf: `reportPlacement`, `pagePlacement`, `containerPlacement`, `relativeToObjectPlacement`)
  - `updateObject`: `object` (oneOf `update<ChartType>Request` schemas)
  - `setParameterValue`: `name` (required), `value` (required)

**Report state note:** the VA v8 spec has no report-state endpoints; saved report states are managed by the Reports API v7 (`/reports/{reportId}/states`, see below). Report modification in VA is done via the operations request above.

**Async export jobs:** each `POST .../export*` returns a job; `GET /jobs/{jobId}` responds with `application/vnd.sas.visual.analytics.report.export.{data|image|package|pdf}.job+json`; job `state` enum: `running`, `completed`, `failed`.

---

## Reports API (v7) — `/reports`

| METHOD | PATH | operationId | summary |
|---|---|---|---|
| GET | / | root | Get a collection of top-level links |
| HEAD | / | headersForRoot | Get header information for the service |
| GET | /reports | getReports | Get a collection of reports |
| POST | /reports | createReport | Create report |
| GET | /reports/{reportId} | getReport | Get a report |
| HEAD | /reports/{reportId} | headersForGetReport | Check report status |
| GET | /reports/{reportId}#resourceSummary | getReportAsResourceSummary | Get resource summary report |
| HEAD | /reports/{reportId}#resourceSummary | headersForGetReportResourceSummary | Check report resource summary status |
| PUT | /reports/{reportId} | updateReport | Update a report |
| DELETE | /reports/{reportId} | deleteReport | Delete a report |
| GET | /reports/{reportId}/content | getContent | Get report content |
| PUT | /reports/{reportId}/content | updateContent | Save report content |
| HEAD | /reports/{reportId}/content | headersForGetContent | Check status of report content |
| PUT | /reports/{reportId}/content#updateContentWithReturn | updateContentWithReturn | Save and return report content |
| GET | /reports/{reportId}/content/version | getContentVersion | Get persisted report content version |
| HEAD | /reports/{reportId}/content/version | headersForGetContentVersion | Check persisted report content version |
| POST | /reports/{reportId}/content/validation#validatePersistedContent | createPersistedContentValidation | Validate the persisted report content schema |
| GET | /reports/{reportId}/content/elements | getContentElements | Get report content elements |
| HEAD | /reports/{reportId}/content/elements | headersForGetContentElements | Check report content elements status |
| GET | /versions | getReportContentVersions | Get available versions of report content |
| GET | /versions/@defaultVersion | getDefaultReportContentVersion | Get the default version of report content |
| GET | /versions/{semanticVersion} | getReportContentVersion | Get the report content version for the given semantic version |
| POST | /validations/name#validateName | createNameValidation | Validate report name |
| GET | /reports/{reportId}/states | getReportStates | Get a collection of report states |
| POST | /reports/{reportId}/states | createReportState | Create report state |
| HEAD | /reports/{reportId}/states | headersForGetReportStates | Check a collection of report states |
| GET | /reports/{reportId}/states/{stateId} | getReportState | Get report state |
| PUT | /reports/{reportId}/states/{stateId} | updateReportState | Update report state |
| DELETE | /reports/{reportId}/states/{stateId} | deleteReportState | Delete report state |
| HEAD | /reports/{reportId}/states/{stateId} | headersForGetReportState | Check report state status |
| GET | /reports/{reportId}/states/{stateId}/content | getReportStateContent | Get report state content |
| PUT | /reports/{reportId}/states/{stateId}/content | updateReportStateContent | Save report state content |
| PUT | /reports/{reportId}/states/{stateId}/content#updateReportStateContentWithReturn | updateReportStateContentWithReturn | Store and return report state content |
| HEAD | /reports/{reportId}/states/{stateId}/content | headersForGetReportStateContent | Check report state content status |
| POST | /content#toJSON | convertContentToJson | Convert content from XML to JSON |
| POST | /content#toXML | convertContentToXml | Convert content from JSON to XML |
| POST | /content/validation#validateAnyContent | validateContent | Validate report content schema |

### Key request shapes

**Create a report — POST /reports?parentFolderUri={folderUri}**
- Query param `parentFolderUri` (string, **required**) — the report is created as a child of this folder.
- Body media: `application/vnd.sas.report+json` (or `application/json`). Report object properties: `name` (required), `description`; server-managed: `id`, `creationTimeStamp`, `createdBy`, `modifiedTimeStamp`, `modifiedBy`, `links[]`, `imageUris` (`icon` required), `version`.
- `PUT /reports/{reportId}` takes the same `application/vnd.sas.report+json` body (rename/update metadata) with required `If-Match` etag header.

**Report content — exact media types:**
- `GET /reports/{reportId}/content` → 200 with `application/vnd.sas.report.content+json` or `application/vnd.sas.report.content+xml` (conditional headers: `If-None-Match`, `If-Modified-Since`).
- `PUT /reports/{reportId}/content` accepts `application/vnd.sas.report.content+json` or `application/vnd.sas.report.content+xml`; headers `If-Match` / `If-Unmodified-Since`; query `copyDependentFiles` (bool — copies dependent file resources). 412/428 returned on precondition failures.
- `PUT .../content#updateContentWithReturn` — same request media; returns the saved content (200/201 with `application/vnd.sas.report.content+json|+xml`).
- Conversion: `POST /content#toJSON` accepts `application/vnd.sas.report.content+xml`; `POST /content#toXML` accepts `application/vnd.sas.report.content+json`; `POST /content/validation#validateAnyContent` accepts either.

**Report states:**
- `POST|PUT /reports/{reportId}/states[/{stateId}]` — media `application/vnd.sas.report.state.info+json`: `label` (string), `primary` (boolean), `reportModifiedTimeStamp` (string).
- State content `GET|PUT /reports/{reportId}/states/{stateId}/content` uses the same `application/vnd.sas.report.content+json|+xml` media types as report content.

**Moving/copying:** the Reports v7 spec defines **no move or copy endpoint**. Folder placement happens only at creation time via the `parentFolderUri` query param (moving between folders is done through the SAS Folders API); report copy is provided by the Visual Analytics API (`PUT /visualAnalytics/reports/{reportId}/copy` with an operations request), and `DELETE /reports/{reportId}` also removes the report from its parent folder.

---

## Report Transforms API (v3) — `/reportTransforms`

| METHOD | PATH | operationId | summary |
|---|---|---|---|
| GET | / | root | Get list of top-level links |
| POST | /dataMappedReports | createDataMappedReport | Change report data source |
| POST | /dataMappedReports/{reportId} | createDataMappedReportOfSavedReport | Change report data source of a saved report |
| PUT | /dataMappedReports/{reportId} | updateDataMappedReportOfSavedReportAndSave | Change report data source of a saved report and save the result |
| GET | /translationWorksheets/{reportId}/{translationLocale} | getTranslationWorksheet | Get translation worksheet for report |
| PUT | /translationWorksheets/{reportId}/{translationLocale} | updateTranslationWorksheet | Update localization in a report |
| POST | /translationWorksheets/{translationLocale}#content | createTranslationWorksheetFromContent | Get localization worksheet |
| GET | /translatedReports/{reportId}/{translationLocale} | getTranslatedReport | Translate a saved report |
| POST | /translatedReports/{translationLocale} | createTranslatedReport | Translate a submitted report |
| GET | /rethemedReports/{reportId}/{themeName} | getRethemedReport | Change theme of existing report |
| POST | /rethemedReports/{themeName} | createRethemedReport | Change theme of submitted report |
| PUT | /commons/validations/translationWorksheets/{reportId}/{translationLocale} | updateTranslationWorksheetValidation | Validate conditional put operations |

### Key request shapes

**createDataMappedReport — POST /dataMappedReports**
- Body media: `application/vnd.sas.report.transform+json`, `application/vnd.sas.report.transform+xml`, `application/json`, `application/xml`.
- Query params: `useSavedReport` (bool, default false — resolve input report from repository), `saveResult` (bool, default false — save transformed report vs return it), `failOnDataSourceError` (bool, default true), `validate` (bool, default true — XML schema validation).
- Transform body properties (full):
  - `id`, `version` (number), `creationTimeStamp`, `createdBy`, `modifiedTimeStamp`, `modifiedBy`
  - `inputReportUri` (string) — source report
  - `resultReportName` (string), `resultParentFolderUri` (string), `resultReport` (report object: `id`, `name` required, `description`, timestamps, `links[]`, `imageUris.icon`, `version`)
  - `dataSources` (array of dataSource): `purpose` (**required**; enum: `original`, `replacement`, `creation`, `modification`), `namePattern` (enum: `uniqueName`, `serverLibraryTable`), `server`, `library`, `table`, `uniqueName`, `replacementLabel`, `dataItemReplacements[]` (`originalName`, `originalColumn`, `replacementColumn` **required**)
  - `schemaValidationStatus` (enum: `schemaValid`, `schemaInvalid`)
  - `evaluationStatus` (enum: `evaluationValid`, `evaluationInvalid`), `evaluation` (array of string — text generated during semantic evaluation)
  - `messages`, `errorMessages` (arrays of codedMessage)
  - `substitutionParameters[]`: `key`, `label`, `site` (enum: `parameterDefinition`, `parameterState`, `urlParameter`), `structure` (enum: `single`, `multiple`, `range`), `type` (enum: `string`, `number`, `date`, `datetime`, `time`, `missing`; default `string`), `values[]`
  - `reportContent` (inline BIRD report: `xmlns` **required**, `label`, `modifiedBy`, `dateCreated`, `dateModified`, `lastModifiedApplicationName`, `createdBy`, `createdApplicationName`, `createdLocale`, `createdVersion`, plus BIRD elements)
  - `links[]`
- `POST|PUT /dataMappedReports/{reportId}` use the same body; query `failOnDataSourceError`; PUT also takes `If-Match` header.

**Translate operations:**
- `GET /translationWorksheets/{reportId}/{translationLocale}` — extract translatable strings (query `validate`, default true).
- `PUT /translationWorksheets/{reportId}/{translationLocale}` — apply translations; body `text/plain` or `application/vnd.sas.report.translation.worksheet+json`; header `If-Match`.
- `POST /translationWorksheets/{translationLocale}#content` — worksheet from submitted content; body `application/vnd.sas.report.content+json|+xml`.
- `GET /translatedReports/{reportId}/{translationLocale}` — returns saved report translated to the locale (query `validate`).
- `POST /translatedReports/{translationLocale}` — translate a submitted report; body is the transform media type; query `saveResult`, `validate`.

**Evaluate operations:** no `/evaluatedReports` path is defined in this v3 spec. Semantic evaluation surfaces as (a) the transform properties `evaluationStatus` (`evaluationValid`/`evaluationInvalid`) and `evaluation[]` (evaluation log text) on transform responses, and (b) a link with `rel: createEvaluatedReport` → `POST /reportTransforms/evaluatedReports` that appears in the spec's link examples (endpoint not documented here).

---

## Insights API (v3) — `/insights`

| METHOD | PATH | operationId | summary |
|---|---|---|---|
| GET | / | root | Get a collection of top-level links |
| POST | /explain | getExplanation | Explains the column in the data source |

### Key request shapes

**POST /explain** — media `application/vnd.sas.insights.explain.definition` (or `application/json`); headers `Accept-Language`, `Accept-Locale`:
- `version` (integer)
- `cas` (**required**): `server` (required), `library` (required), `table` (required), `sessionId` (uuid, optional)
- `targetVariable` (string, **required**)
- `includeVariableDescription` (bool, default true), `includeOutlierDescription` (bool, default false) — at least one must be true
- `useMissing` (bool, default true), `dateVariable` (string — enables forecast insights), `includeVariableScreeningResults` (bool, default true)
- 200 response media: `application/vnd.sas.insights.explain.result` — `variableDescription`, `outlierDescription`, `forecastDescription`, `variableScreeningResults[]`, `warnings[]`.
