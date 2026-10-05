// Fixed synthetic public sample. Never reads a private job or invokes a provider.
export const DEMO_JOB_ID = "demo";
export const DEMO_META = {
  invention_idea: "Synthetic demo: a humidity-aware irrigation controller",
  created_at: "2026-01-01T00:00:00Z",
};
export const DEMO_RESULTS = {
  final_report:
    "# Synthetic analysis brief\n\nThis fixed example illustrates a saved report. No patent search or AI generation was performed. Novelty and patentability have not been assessed.",
  retrieval_outcome: "complete",
  coverage_warnings: [],
  clusters: [
    {
      theme_name: "Sensor feedback (synthetic)",
      description:
        "Example grouping for soil-moisture feedback. These are sample descriptions, not retrieved prior art.",
      patent_ids: [],
    },
    {
      theme_name: "Adaptive scheduling (synthetic)",
      description:
        "Example grouping for adjusting irrigation schedules. Sign in to analyze your own invention.",
      patent_ids: [],
    },
  ],
  white_space_analysis:
    "### Gap 1: Local sensor calibration (synthetic demo)\n**Viability: Unknown**\nA fixed example opportunity: calibrate the sensor to local soil conditions. This demo makes no novelty or patentability claim.\n",
  citation_links: [],
};
export const DEMO_IDEA = {
  invention_name: "Synthetic calibration controller",
  one_liner: "A fixed sample of an irrigation sensor calibration workflow.",
  mechanism:
    "Compare repeated local moisture readings against a reference measurement before scheduling irrigation.",
  key_differentiators: ["Sample local calibration", "Sample feedback loop"],
  why_novel: "Novelty has not been assessed; this is deterministic demo data.",
};
export const DEMO_CLAIMS = [
  {
    patent_id: "DEMO-EXAMPLE",
    title: "Synthetic claim comparison example",
    likely_claims: [
      "Sample claim wording for a sensor-controlled irrigation method.",
    ],
    overlap_level: "none" as const,
    overlap_explanation:
      "No patent claims were retrieved or analyzed for this demo.",
    differentiators:
      "Sign in to run a private analysis. This sample is not patent evidence.",
  },
];

export const DEMO_EVIDENCE: import("./api").EvidenceResponse = {
  evidence_version: 1, requested_jurisdiction: "all", warnings: [],
  clusters: DEMO_RESULTS.clusters, citation_links: [],
  patents: [{
    patent_id: "synthetic:DEMO-EXAMPLE", title: "Synthetic irrigation controller",
    evidence_status: "available", evidence: { version: 1, observations: [{
      provider: "synthetic", provider_record_id: "DEMO-EXAMPLE", publication_id: null,
      source_url: null, retrieved_at: null, matching_queries: [],
      text: "A synthetic irrigation controller uses local humidity readings to adjust watering schedules.",
      text_type: "synthetic", language: "en",
      dates: { priority: null, filing: null, publication: null },
      requested_jurisdiction: "all", jurisdiction_filter: null,
      coverage_limitations: ["Fixed synthetic demo; no patent retrieval or filtering was performed."],
    }] },
  }],
};
