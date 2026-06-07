# format_final.R
# Post-processes datacenter_merged_final.xlsx:
#   - Color-codes rows by confidence tier
#   - Adds a Methodology tab
#   - Adds a Confidence Legend tab
#
# Run after datacenter_merge.R + echo_phase4.R:
#   source("format_final.R")
#
# Requires: openxlsx (already used in pipeline)

library(openxlsx)

FINAL_PATH <- "datacenter_merged_final.xlsx"

# ── Confidence tier palette ────────────────────────────────────────────────────
# Desaturated quadrant anchored to navy header (#1F4E79).
# All four are readable with dark text; none read as traffic-light signals.
COL_HIGH   <- "#D4E8D0"   # muted sage       — grounded, measured
COL_MEDIUM <- "#D3E4F5"   # dusty steel blue — analytical, moderate
COL_LOW    <- "#FAF0D6"   # warm parchment   — soft uncertainty
COL_NONE   <- "#EFEFEF"   # cool light grey  — absent signal
COL_HEADER <- "#1F4E79"   # navy             — existing header (unchanged)

TIER_MAP <- list(
  high   = c("sec_filing", "exact"),
  medium = c("fuzzy", "investor_supplement_metro_avg",
             "investor_supplement_portfolio_avg",
             "echo_air_permit_heuristic"),
  low    = c("operator_bracket_hyperscaler", "operator_bracket_major_colo",
             "operator_bracket_regional_colo", "operator_bracket_specialty",
             "operator_bracket_telco_pop", "operator_bracket_crypto_miner",
             "operator_bracket_property_manager", "echo_operator_bracket"),
  none   = c("operator_bracket_unknown", "not_in_filing")
)

# ══════════════════════════════════════════════════════════════════════════════
# LOAD
# ══════════════════════════════════════════════════════════════════════════════
cat("Loading", FINAL_PATH, "...\n")
wb    <- loadWorkbook(FINAL_PATH)
atlas <- readWorkbook(wb, sheet = "Datacenters")
cat(sprintf("  %d rows, %d columns\n\n", nrow(atlas), ncol(atlas)))

conf_col_idx <- which(names(atlas) == "source_confidence")
if (length(conf_col_idx) == 0) stop("source_confidence column not found")

# ══════════════════════════════════════════════════════════════════════════════
# STYLES
# ══════════════════════════════════════════════════════════════════════════════
hdr_style <- createStyle(
  fontColour = "#FFFFFF", fgFill = COL_HEADER,
  textDecoration = "Bold", border = "Bottom", wrapText = FALSE
)

make_row_style <- function(fill) {
  createStyle(fgFill = fill, border = "Bottom",
              borderColour = "#D9D9D9", borderStyle = "thin")
}

styles <- list(
  high   = make_row_style(COL_HIGH),
  medium = make_row_style(COL_MEDIUM),
  low    = make_row_style(COL_LOW),
  none   = make_row_style(COL_NONE)
)

# ══════════════════════════════════════════════════════════════════════════════
# APPLY ROW COLORS TO DATACENTERS SHEET
# ══════════════════════════════════════════════════════════════════════════════
n_cols <- ncol(atlas)

classify_row <- function(conf) {
  if (conf %in% TIER_MAP$high)   return("high")
  if (conf %in% TIER_MAP$medium) return("medium")
  if (conf %in% TIER_MAP$low)    return("low")
  return("none")
}

tiers <- vapply(atlas$source_confidence, classify_row, character(1))
tier_counts <- table(tiers)
cat("Row color distribution:\n")
print(tier_counts)
cat("\n")

# Apply per-tier in bulk (much faster than row-by-row)
for (tier_name in names(styles)) {
  rows <- which(tiers == tier_name) + 1L   # +1 for header row
  if (length(rows) == 0) next
  addStyle(wb, "Datacenters", styles[[tier_name]],
           rows = rows, cols = seq_len(n_cols),
           gridExpand = TRUE, stack = TRUE)
}

# ══════════════════════════════════════════════════════════════════════════════
# CONFIDENCE LEGEND TAB
# ══════════════════════════════════════════════════════════════════════════════
legend_df <- data.frame(
  Tier = c("HIGH", "HIGH", "MEDIUM", "MEDIUM", "MEDIUM", "MEDIUM",
           "LOW", "LOW", "LOW", "LOW", "LOW", "LOW", "LOW",
           "NONE", "NONE"),
  source_confidence = c(
    "sec_filing", "exact",
    "fuzzy", "investor_supplement_metro_avg",
    "investor_supplement_portfolio_avg", "echo_air_permit_heuristic",
    "operator_bracket_hyperscaler", "operator_bracket_major_colo",
    "operator_bracket_regional_colo", "operator_bracket_specialty",
    "operator_bracket_telco_pop", "operator_bracket_crypto_miner",
    "echo_operator_bracket",
    "operator_bracket_unknown", "not_in_filing"
  ),
  Description = c(
    "Exact MW from SEC 10-K filing (Core Scientific FY2025)",
    "ENERGY STAR exact name match — floor space converted to kW at 130 W/sq ft",
    "ENERGY STAR fuzzy name match — same conversion, lower name-match confidence",
    "Digital Realty metro-average MW per site (1Q26 investor supplement)",
    "Iron Mountain portfolio average (488 MW / 31 sites)",
    "EPA ECHO air permit type + operator pattern + IAD building count + county floor",
    "Operator bracket — hyperscaler published US capacity estimate (~75–200 MW)",
    "Operator bracket — major colo industry average (~15–80 MW)",
    "Operator bracket — regional colo industry average (~5–15 MW)",
    "Operator bracket — specialty operator estimate",
    "Operator bracket — telecom network PoP, low MW (~1–3 MW)",
    "Operator bracket — public crypto miner estimate",
    "EPA ECHO NAICS 518210 facility appended to Atlas, operator bracket applied",
    "No operator data — generic 5 MW default applied",
    "Facility in Atlas but absent from most recent SEC filing; may be decommissioned"
  ),
  Typical_MW_Range = c(
    "Site-specific", "Derived from floor space", "Derived from floor space",
    "Metro average", "15.7 MW avg",
    "4–200 MW (permit+operator+county)",
    "75–200 MW", "15–80 MW", "5–15 MW", "10–50 MW", "1–3 MW", "20–100 MW",
    "5–100 MW",
    "5 MW", "Unknown"
  ),
  stringsAsFactors = FALSE
)

if ("Confidence Legend" %in% names(wb)) removeWorksheet(wb, "Confidence Legend")
addWorksheet(wb, "Confidence Legend", tabColour = "#554F47")
writeData(wb, "Confidence Legend", legend_df, na.string = "")

# Header
addStyle(wb, "Confidence Legend", hdr_style,
         rows = 1, cols = 1:4, gridExpand = TRUE)

# Tier fill colors
tier_fills <- c(HIGH = COL_HIGH, MEDIUM = COL_MEDIUM,
                LOW = COL_LOW, NONE = COL_NONE)
for (tier_name in names(tier_fills)) {
  rows <- which(legend_df$Tier == tier_name) + 1L
  if (length(rows) == 0) next
  addStyle(wb, "Confidence Legend",
           make_row_style(tier_fills[tier_name]),
           rows = rows, cols = 1:4, gridExpand = TRUE, stack = TRUE)
}

setColWidths(wb, "Confidence Legend", cols = 1:4,
             widths = c(10, 38, 62, 26))
freezePane(wb, "Confidence Legend", firstRow = TRUE)

# ══════════════════════════════════════════════════════════════════════════════
# METHODOLOGY TAB
# ══════════════════════════════════════════════════════════════════════════════
method_rows <- c(
    "OVERVIEW",
    "US Data Center Energy Atlas — Enriched Dataset",
    paste("Produced by CITS, University of Georgia |", format(Sys.Date(), "%B %Y")),
    "Combines the Global Data Center Atlas with EPA, EIA, and operator data to estimate per-facility power draw.",
    "",
    "BASE LAYER",
    "Source: Global Data Center Atlas (datacenters.com)",
    "3,368 US facilities with name, operator, address, latitude/longitude. No power data in source.",
    "",
    "PHASE 1 — ENERGY STAR MATCH",
    "Source: EPA ENERGY STAR Certified Data Centers list",
    "Facility names fuzzy-matched (Jaro-Winkler, threshold 90) against Atlas by state.",
    "Matched facilities: floor space (sq ft) converted to kW at 130 W/sq ft (PUE 1.3 assumption).",
    "35 exact matches (HIGH confidence). 113 fuzzy matches (MEDIUM confidence).",
    "",
    "PHASE 2 — OPERATOR BRACKETS",
    "Source: Public earnings reports, SEC filings, industry research",
    "Pattern-matched Atlas operator names against a tiered bracket table.",
    "Tiers: hyperscaler (75-200 MW avg), major colo (15-80 MW), regional colo (5-15 MW),",
    "       telecom PoP (1-3 MW), crypto miner (20-75 MW).",
    "Brackets represent industry averages — not site-specific measurements.",
    "Confidence: LOW.",
    "",
    "PHASE 2b — SEC FILINGS",
    "Source: Core Scientific FY2025 Form 10-K (SEC EDGAR)",
    "Exact contracted MW per facility disclosed in annual filing.",
    "8 facilities. Confidence: HIGH.",
    "",
    "PHASE 2c — INVESTOR SUPPLEMENTS",
    "Source: Digital Realty 1Q2026 supplemental; Iron Mountain investor presentation",
    "Digital Realty: metro-level MW/site count. Iron Mountain: portfolio average.",
    "Confidence: MEDIUM.",
    "",
    "PHASE 2d — EPA ECHO APPEND",
    "Source: EPA ECHO Exporter (echo.epa.gov), NAICS code 518210",
    "693 NAICS 518210 facilities in ECHO. ~52 not present in Atlas — appended as new rows.",
    "Operator brackets applied to new rows. Confidence: LOW.",
    "",
    "PHASE 3 — CAMPUS CLUSTERING",
    "Method: BFS graph clustering within 1 km radius, per operator",
    "Multi-building campuses identified and bracket MW split among buildings.",
    "Allocation: proportional to floor space (if ENERGY STAR data exists), otherwise equal split.",
    "Prevents bracket MW from being counted once per building on shared campuses.",
    "",
    "PHASE 4 — AIR PERMIT HEURISTIC",
    "Source: EPA ECHO air permit classifications for NAICS 518210 facilities",
    "458 facilities have CAA air permits (backup diesel generators require permitting).",
    "Permit tier (Major / 80% Synthetic Minor / Synthetic Minor / Minor) used as MW signal.",
    "Amazon IAD naming convention decoded to building count (IAD-500/501 = 2 bldgs x 36 MW).",
    "County-level floor applied to unknown operators in proven hyperscaler corridors.",
    "(Loudoun/Prince William VA = 50 MW floor; Fairfax/Cook/Maricopa = 20 MW floor)",
    "",
    "LIMITATIONS",
    "1. Power estimates are modeled — not metered. Only sec_filing and exact are observational.",
    "2. Operator brackets are industry averages; individual facilities vary significantly.",
    "3. Campus clustering uses 1 km threshold — may under- or over-consolidate in dense markets.",
    "4. ECHO NAICS 518210 is broad; some facilities are hosting providers, not hyperscale DCs.",
    "5. Press-release capacity (announced MW) is not used — estimates reflect operational signal only."
)

# Section header rows: all-caps entries that match phase/section names
SECTION_LABELS <- c("OVERVIEW", "BASE LAYER", "PHASE 1 — ENERGY STAR MATCH",
                     "PHASE 2 — OPERATOR BRACKETS", "PHASE 2b — SEC FILINGS",
                     "PHASE 2c — INVESTOR SUPPLEMENTS", "PHASE 2d — EPA ECHO APPEND",
                     "PHASE 3 — CAMPUS CLUSTERING", "PHASE 4 — AIR PERMIT HEURISTIC",
                     "LIMITATIONS")

method_text <- data.frame(Content = method_rows, stringsAsFactors = FALSE)
is_section_row <- method_rows %in% SECTION_LABELS

if ("Methodology" %in% names(wb)) removeWorksheet(wb, "Methodology")
addWorksheet(wb, "Methodology", tabColour = "#004E60")
writeData(wb, "Methodology", method_text, na.string = "", colNames = FALSE)

section_style <- createStyle(
  textDecoration = "Bold", fontColour = "#FFFFFF",
  fgFill = "#004E60", fontSize = 10
)
body_style  <- createStyle(fontSize = 10, wrapText = TRUE)
title_style <- createStyle(textDecoration = "Bold", fontSize = 14,
                            fontColour = COL_HEADER)

addStyle(wb, "Methodology", title_style, rows = 1, cols = 1)
addStyle(wb, "Methodology", body_style,
         rows = seq_len(nrow(method_text)), cols = 1,
         gridExpand = TRUE, stack = FALSE)
addStyle(wb, "Methodology", section_style,
         rows = which(is_section_row), cols = 1,
         gridExpand = FALSE, stack = TRUE)

setColWidths(wb, "Methodology", cols = 1, widths = 110)
setRowHeights(wb, "Methodology",
              rows    = seq_len(nrow(method_text)),
              heights = rep(16, nrow(method_text)))

# ══════════════════════════════════════════════════════════════════════════════
# SAVE
# ══════════════════════════════════════════════════════════════════════════════
saveWorkbook(wb, FINAL_PATH, overwrite = TRUE)

cat(sprintf("Saved: %s\n", FINAL_PATH))
cat(sprintf("  Sheets: %s\n", paste(names(wb), collapse = ", ")))
cat(sprintf("  HIGH rows:   %d\n", sum(tiers == "high")))
cat(sprintf("  MEDIUM rows: %d\n", sum(tiers == "medium")))
cat(sprintf("  LOW rows:    %d\n", sum(tiers == "low")))
cat(sprintf("  NONE rows:   %d\n", sum(tiers == "none")))
