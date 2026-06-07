# echo_phase4.R
# Phase 4: EPA ECHO Air Permit → Capacity Refinement
#
# Reads the already-downloaded ECHO_EXPORTER.csv and extracts NAICS 518210
# (data centers) with CAA air permits.  Uses permit classification tier,
# operator name pattern, and building-count heuristics to sharpen est_power_kw
# relative to the generic operator brackets set in Phase 2.
#
# Output:
#   echo_phase4_targets.csv   — all 458 air-permitted DC facilities, enriched
#   (optionally updates datacenter_merged_final.xlsx in place)
#
# Usage:
#   source("echo_phase4.R")          # prints summary, writes CSV
#
# Install once:
#   install.packages(c("readr", "dplyr", "openxlsx", "stringr", "purrr"))

library(readr)
library(dplyr)
library(purrr)
library(stringr)
library(openxlsx)

# ── Paths ─────────────────────────────────────────────────────────────────────
ECHO_CSV    <- "echo_tmp/ECHO_EXPORTER.csv"
FINAL_XLSX  <- "datacenter_merged_final.xlsx"
OUT_CSV     <- "echo_phase4_targets.csv"

# ── Valid US state abbreviations ──────────────────────────────────────────────
VALID_STATES <- c(
  "AL","AK","AZ","AR","CA","CO","CT","DE","FL","GA","HI","ID",
  "IL","IN","IA","KS","KY","LA","ME","MD","MA","MI","MN","MS","MO","MT",
  "NE","NV","NH","NJ","NM","NY","NC","ND","OH","OK","OR","PA","RI","SC",
  "SD","TN","TX","UT","VT","VA","WA","WV","WI","WY","DC"
)

# ══════════════════════════════════════════════════════════════════════════════
# 1. LOAD & FILTER
# ══════════════════════════════════════════════════════════════════════════════
cat("Loading ECHO_EXPORTER.csv ...\n")
echo_raw <- read_csv(ECHO_CSV,
  col_types = cols(.default = col_character()),
  progress  = FALSE
)
cat(sprintf("  %d total rows\n", nrow(echo_raw)))

echo_dc <- echo_raw |>
  filter(str_detect(FAC_NAICS_CODES, "518210")) |>
  filter(AIR_FLAG == "Y") |>
  filter(FAC_STATE %in% VALID_STATES) |>
  filter(!is.na(FAC_LAT), FAC_LAT != "0",
         !is.na(FAC_LONG), FAC_LONG != "0")

cat(sprintf("  %d NAICS 518210 + AIR_FLAG=Y + US coords\n\n", nrow(echo_dc)))

# ══════════════════════════════════════════════════════════════════════════════
# 2. PERMIT TIER
# ══════════════════════════════════════════════════════════════════════════════
# Clean the multi-value permit type field to a single dominant tier
classify_permit_tier <- function(raw) {
  case_when(
    str_detect(raw, "Major")                                    ~ "major",
    str_detect(raw, "80%")                                      ~ "synthetic_minor_80pct",
    str_detect(raw, "Synthetic Minor|Synthetic_Minor",
               negate = FALSE)                                  ~ "synthetic_minor",
    str_detect(raw, "Minor")                                    ~ "minor",
    TRUE                                                        ~ "unknown"
  )
}

echo_dc <- echo_dc |>
  mutate(permit_tier = classify_permit_tier(CAA_PERMIT_TYPES))

cat("Permit tier distribution:\n")
print(count(echo_dc, permit_tier, sort = TRUE))
cat("\n")

# ══════════════════════════════════════════════════════════════════════════════
# 3. OPERATOR RECOGNITION
# ══════════════════════════════════════════════════════════════════════════════
# Maps ECHO facility name → canonical operator string.
# Priority: exact hyperscaler patterns first, then broader patterns.

OPERATOR_PATTERNS <- tribble(
  ~pattern,                         ~operator,         ~tier,
  "AMAZON|AWS|AMZN",                "Amazon",          "hyperscaler",
  "MICROSOFT|MSFT",                 "Microsoft",       "hyperscaler",
  "GOOGLE",                         "Google",          "hyperscaler",
  "META |FACEBOOK",                 "Meta",            "hyperscaler",
  "APPLE INC|APPLE DATA",           "Apple",           "hyperscaler",
  "EQUINIX",                        "Equinix",         "major_colo",
  "DIGITAL REALTY|DUPONT FABROS",   "Digital Realty",  "major_colo",
  "CYRUSONE|CYRUS ONE",             "CyrusOne",        "major_colo",
  "QTS |QUALITY TECHNOLOGY",        "QTS",             "major_colo",
  "NTT ",                           "NTT",             "major_colo",
  "IRON MOUNTAIN",                  "Iron Mountain",   "major_colo",
  "STACK INFRA",                    "Stack Infra",     "major_colo",
  "VANTAGE DATA",                   "Vantage",         "major_colo",
  "EDGECORE",                       "EdgeCore",        "major_colo",
  "CORESITE",                       "CoreSite",        "major_colo",
  "COMPASS DATA|COMPASS DATACENTER","Compass",         "major_colo",
  "SWITCH ",                        "Switch",          "major_colo",
  "DATABANK",                       "DataBank",        "regional_colo",
  "FLEXENTIAL",                     "Flexential",      "regional_colo",
  "TIERPOINT",                      "TierPoint",       "regional_colo",
  "COLOGIX",                        "Cologix",         "regional_colo",
  "ZAYO",                           "Zayo",            "telco_pop",
  "COGENT",                         "Cogent",          "telco_pop",
  "CRUSOE",                         "Crusoe",          "crypto_miner",
  "APPLIED DIGITAL",                "Applied Digital", "crypto_miner",
  "TERAWULF",                       "TeraWulf",        "crypto_miner",
  # Amazon airport-code campuses outside IAD (CMH=Columbus, PDX=Portland, etc.)
  "^CMH[0-9]|^PDX[0-9]|^DFW[0-9]|^SFO[0-9]|^ORD[0-9]|^BOS[0-9]",
                                    "Amazon",          "hyperscaler",
  "SUPERNAP|SUPER NAP",             "Switch",          "major_colo",
  "RACKSPACE",                      "Rackspace",       "regional_colo",
  "T5 DATA|T5@|T5 AT ",            "T5 Data Centers", "major_colo",
  "VIAWEST|VIA WEST|PEAK 10|PEAK10","ViaWest",         "regional_colo",
  "ENSONO",                         "Ensono",          "regional_colo",
  "123NET",                         "123.net",         "regional_colo",
  "MAGURO|OSMIUM|SICULUS|GABLE |RAVEN NORSE|SIDECAT|MONTAUK|MAGELLAN|GROOT|AGATE|TAPAHA|HATCHWORK",
                                    "Unknown Miner",   "crypto_miner"
)

match_operator <- function(name) {
  n <- toupper(name)
  for (i in seq_len(nrow(OPERATOR_PATTERNS))) {
    if (str_detect(n, OPERATOR_PATTERNS$pattern[i])) {
      return(list(op   = OPERATOR_PATTERNS$operator[i],
                  tier = OPERATOR_PATTERNS$tier[i]))
    }
  }
  list(op = NA_character_, tier = "unknown")
}

ops   <- lapply(echo_dc$FAC_NAME, match_operator)
echo_dc <- echo_dc |>
  mutate(
    echo_operator = map_chr(ops, "op"),
    echo_op_tier  = map_chr(ops, "tier")
  )

cat("Operator recognition:\n")
print(count(echo_dc, echo_op_tier, sort = TRUE))
cat("\n")

# ══════════════════════════════════════════════════════════════════════════════
# 4. AMAZON IAD BUILDING-COUNT HEURISTIC
# ══════════════════════════════════════════════════════════════════════════════
# Amazon names facility permit groups like "IAD-500/501" or
# "IAD-667, IAD-668, IAD-669, IAD-670, IAD-671".  Count the dash-delimited
# numeric tokens to estimate building count per permit (one permit often covers
# a multi-building campus).  Each IAD building ≈ 36 MW IT load.

count_iad_buildings <- function(name) {
  # Matches IAD-500, CMH072, PDX1, etc. — any 3-letter airport code + digits
  hits <- str_extract_all(name, "[A-Z]{3}-?[0-9]+")[[1]]
  if (length(hits) == 0) return(NA_integer_)
  length(hits)
}

echo_dc <- echo_dc |>
  mutate(
    iad_building_count = if_else(
      echo_operator == "Amazon",
      map_int(FAC_NAME, count_iad_buildings),
      NA_integer_
    )
  )

cat("Amazon IAD building-count distribution:\n")
echo_dc |>
  filter(!is.na(iad_building_count)) |>
  count(iad_building_count, sort = TRUE) |>
  print()
cat("\n")

# ══════════════════════════════════════════════════════════════════════════════
# 5. CAPACITY ESTIMATE (MW)
# ══════════════════════════════════════════════════════════════════════════════
# Hierarchy: building-count > operator+permit tier > permit tier only
#
# MW per IAD building: ~36 MW (Amazon's ~30 MW IT + ~20% overhead, rounded)
# Sources: AWS sustainability reports, Loudoun County permits, press coverage
#
# Permit tier defaults (no known operator):
#   major                 → 75 MW  (above 100 t/yr NOx; large facility)
#   synthetic_minor_80pct → 30 MW  (designed to stay just under major threshold)
#   synthetic_minor       → 12 MW
#   minor                 → 4 MW

MW_PER_IAD_BLDG <- 36

tier_mw_defaults <- c(
  major                 = 75,
  synthetic_minor_80pct = 30,
  synthetic_minor       = 12,
  minor                 = 4,
  unknown               = 5
)

# Operator + tier overrides (where we have better intel)
operator_tier_mw <- tribble(
  ~echo_operator, ~permit_tier,            ~mw_est,
  "Amazon",       "major",                 200,
  "Amazon",       "synthetic_minor_80pct",  NA,  # use building count instead
  "Amazon",       "synthetic_minor",        72,  # 2 buildings default
  "Amazon",       "minor",                  36,
  "Microsoft",    "major",                 150,
  "Microsoft",    "synthetic_minor_80pct",  75,
  "Microsoft",    "synthetic_minor",        40,
  "Microsoft",    "minor",                  20,
  "Google",       "major",                 150,
  "Google",       "synthetic_minor_80pct",  80,
  "Google",       "synthetic_minor",        40,
  "Meta",         "major",                 200,
  "Meta",         "synthetic_minor_80pct", 100,
  "Apple",        "major",                 150,
  "Apple",        "synthetic_minor_80pct",  75,
  "Equinix",      "major",                  30,
  "Equinix",      "synthetic_minor_80pct",  18,
  "Equinix",      "synthetic_minor",        12,
  "Equinix",      "minor",                   8,
  "Digital Realty","major",                 50,
  "Digital Realty","synthetic_minor_80pct", 30,
  "CyrusOne",     "major",                  80,
  "CyrusOne",     "synthetic_minor_80pct",  50,
  "QTS",          "major",                  80,
  "QTS",          "synthetic_minor_80pct",  50,
  "NTT",          "major",                  35,
  "NTT",          "synthetic_minor_80pct",  25,
  "Switch",       "major",                 100,
  "Switch",       "synthetic_minor_80pct",  60,
  "Rackspace",    "major",                  30,
  "Rackspace",    "synthetic_minor_80pct",  15,
  "T5 Data Centers","major",                50,
  "T5 Data Centers","synthetic_minor_80pct",30
)

`%||%` <- function(a, b) if (is.null(a) || is.na(a)) b else a

estimate_mw_phase4 <- function(op, op_tier, ptier, iad_n) {
  # 1. Amazon IAD with building count
  if (!is.na(op) && op == "Amazon" && !is.na(iad_n) && iad_n > 0) {
    return(iad_n * MW_PER_IAD_BLDG)
  }
  # 2. Operator + permit tier lookup
  if (!is.na(op) && !is.na(ptier)) {
    hit <- operator_tier_mw |>
      filter(.data$echo_operator == op, .data$permit_tier == ptier) |>
      pull(mw_est)
    if (length(hit) == 1 && !is.na(hit)) return(hit)
  }
  # 3. Permit tier default
  unname(tier_mw_defaults[ptier %||% "unknown"])
}

echo_dc <- echo_dc |>
  rowwise() |>
  mutate(
    phase4_mw_est = estimate_mw_phase4(
      echo_operator, echo_op_tier, permit_tier, iad_building_count
    )
  ) |>
  ungroup()

# ══════════════════════════════════════════════════════════════════════════════
# 5b. COUNTY-LEVEL FLOOR ADJUSTMENT
# Unknown-operator facilities in proven hyperscaler/major-colo counties get a
# MW floor lifted above the permit-tier default.  Floors only apply to unknowns
# — named operators keep their own estimates.
# ══════════════════════════════════════════════════════════════════════════════

# Normalise county: strip "COUNTY" suffix, trim, uppercase
norm_county <- function(x) {
  x |> toupper() |> trimws() |>
    sub("\\s+COUNTY$", "", x = _, perl = TRUE) |>
    trimws()
}

# County tier lookup: state + normalised county → tier
# hyperscaler_zone: floor 50 MW  |  major_colo_zone: 20 MW  |  regional_hub: 10 MW
county_tier_table <- tribble(
  ~state, ~county_norm,       ~county_tier,
  # Virginia — Northern Virginia corridor
  "VA",   "LOUDOUN",          "hyperscaler_zone",
  "VA",   "PRINCE WILLIAM",   "hyperscaler_zone",
  "VA",   "FAIRFAX",          "major_colo_zone",
  "VA",   "ARLINGTON",        "major_colo_zone",
  "VA",   "FAUQUIER",         "regional_hub",
  "VA",   "CULPEPER",         "regional_hub",
  # Maryland — DC corridor
  "MD",   "MONTGOMERY",       "major_colo_zone",
  "MD",   "PRINCE GEORGE'S",  "major_colo_zone",
  # Illinois — Chicago
  "IL",   "COOK",             "major_colo_zone",
  "IL",   "DUPAGE",           "major_colo_zone",
  # Arizona — Phoenix / Chandler
  "AZ",   "MARICOPA",         "hyperscaler_zone",
  # Ohio — Columbus (Amazon CMH)
  "OH",   "FRANKLIN",         "hyperscaler_zone",
  "OH",   "LICKING",          "hyperscaler_zone",
  # Iowa — Des Moines (Microsoft)
  "IA",   "POLK",             "hyperscaler_zone",
  # Nebraska — Omaha
  "NE",   "SARPY",            "major_colo_zone",
  "NE",   "DOUGLAS",          "major_colo_zone",
  # Texas — DFW
  "TX",   "TARRANT",          "major_colo_zone",
  "TX",   "DALLAS",           "major_colo_zone",
  # Georgia — Atlanta
  "GA",   "FULTON",           "major_colo_zone",
  "GA",   "DOUGLAS",          "major_colo_zone",
  # Colorado — Denver / Aurora
  "CO",   "ARAPAHOE",         "major_colo_zone",
  "CO",   "DENVER",           "major_colo_zone",
  "CO",   "DOUGLAS",          "major_colo_zone",
  # Nevada — Las Vegas (Switch SuperNAP)
  "NV",   "CLARK",            "major_colo_zone",
  # North Carolina — Charlotte / RTP
  "NC",   "MECKLENBURG",      "major_colo_zone",
  "NC",   "WAKE",             "regional_hub",
  # Pennsylvania — Philadelphia suburbs
  "PA",   "MONTGOMERY",       "major_colo_zone",
  "PA",   "NORTHAMPTON",      "regional_hub",
  # Indiana — Whitestown / South Bend (Amazon)
  "IN",   "BOONE",            "hyperscaler_zone",
  "IN",   "ST JOSEPH",        "hyperscaler_zone",
  # Wyoming — Cheyenne (Microsoft)
  "WY",   "LARAMIE",          "hyperscaler_zone"
)

county_floor_mw <- c(
  hyperscaler_zone = 50,
  major_colo_zone  = 20,
  regional_hub     = 10
)

echo_dc <- echo_dc |>
  mutate(
    county_norm = norm_county(FAC_COUNTY),
    county_tier = {
      left_join(
        data.frame(state = FAC_STATE, county_norm = county_norm,
                   row_id = seq_len(n()), stringsAsFactors = FALSE),
        county_tier_table,
        by = c("state", "county_norm")
      ) |>
        arrange(row_id) |>
        pull(county_tier)
    },
    county_floor    = coalesce(county_floor_mw[county_tier], 0),
    # Only apply floor to unknown operators — named operators keep their estimate
    phase4_mw_est = if_else(
      echo_op_tier == "unknown",
      pmax(phase4_mw_est, county_floor),
      phase4_mw_est
    )
  )

cat("County tier applied to unknown-operator facilities:\n")
echo_dc |>
  filter(echo_op_tier == "unknown", !is.na(county_tier)) |>
  count(FAC_STATE, county_norm, county_tier, sort = TRUE) |>
  print(n = 20)
cat("\n")

cat("Phase 4 MW estimate distribution (percentiles):\n")
quantile(echo_dc$phase4_mw_est, c(0, .1, .25, .5, .75, .9, 1), na.rm = TRUE) |>
  print()
cat(sprintf("\nSum total Phase 4 estimate: %.1f GW\n\n",
            sum(echo_dc$phase4_mw_est, na.rm = TRUE) / 1000))

# ══════════════════════════════════════════════════════════════════════════════
# 6. ASSEMBLE OUTPUT TABLE
# ══════════════════════════════════════════════════════════════════════════════
echo_phase4_out <- echo_dc |>
  transmute(
    echo_registry_id    = REGISTRY_ID,
    echo_name           = FAC_NAME,
    echo_operator,
    echo_op_tier,
    state               = FAC_STATE,
    city                = FAC_CITY,
    address             = FAC_STREET,
    lat                 = as.numeric(FAC_LAT),
    lon                 = as.numeric(FAC_LONG),
    caa_permit_type     = CAA_PERMIT_TYPES,
    permit_tier,
    air_permit_ids      = AIR_IDS,
    npdes_flag          = NPDES_FLAG == "Y",
    iad_building_count,
    county_norm,
    county_tier,
    phase4_mw_est,
    phase4_kw_est       = phase4_mw_est * 1000,
    dfr_url             = DFR_URL,
    source_confidence   = "echo_air_permit_heuristic"
  ) |>
  arrange(state, desc(phase4_mw_est))

write_csv(echo_phase4_out, OUT_CSV, na = "")
cat(sprintf("Wrote %s  (%d rows)\n", OUT_CSV, nrow(echo_phase4_out)))

# ══════════════════════════════════════════════════════════════════════════════
# 7. MERGE BACK INTO FINAL XLSX (optional — updates Sheet 1 in place)
# ══════════════════════════════════════════════════════════════════════════════
# Spatial join: for each Phase 4 row, find nearest row in the existing Atlas
# dataset that is already in the Excel. If within 500 m AND the current
# source_confidence is a bracket/unknown, upgrade est_power_kw with the Phase 4
# estimate and set source_confidence = "echo_air_permit_heuristic".

merge_phase4_into_excel <- function(xlsx_path = FINAL_XLSX,
                                    p4         = echo_phase4_out,
                                    dist_km    = 0.5) {
  if (!file.exists(xlsx_path)) {
    cat("FINAL_XLSX not found — skipping merge\n"); return(invisible(NULL))
  }
  cat("\nMerging Phase 4 into", xlsx_path, "...\n")
  wb    <- loadWorkbook(xlsx_path)
  atlas <- readWorkbook(wb, sheet = "Datacenters")

  # Rows we are willing to update — brackets AND previous Phase 4 runs
  UPGRADEABLE <- c(
    "operator_bracket_hyperscaler",
    "operator_bracket_major_colo",
    "operator_bracket_regional_colo",
    "operator_bracket_specialty",
    "operator_bracket_telco_pop",
    "operator_bracket_crypto_miner",
    "operator_bracket_unknown",
    "echo_operator_bracket",
    "echo_air_permit_heuristic"   # allow re-runs to update their own estimates
  )

  a_lat  <- suppressWarnings(as.numeric(atlas$Latitude))
  a_lon  <- suppressWarnings(as.numeric(atlas$Longitude))

  n_updated <- 0L
  for (i in seq_len(nrow(p4))) {
    if (is.na(p4$lat[i]) || is.na(p4$lon[i])) next
    dlat <- (a_lat - p4$lat[i]) * 111.0
    dlon <- (a_lon - p4$lon[i]) * 111.0 * cos(p4$lat[i] * pi / 180)
    d    <- sqrt(dlat^2 + dlon^2)
    best <- which.min(d)
    if (d[best] > dist_km) next
    if (!atlas$source_confidence[best] %in% UPGRADEABLE) next

    atlas$est_power_kw[best]       <- p4$phase4_kw_est[i]
    atlas$source_confidence[best]  <- "echo_air_permit_heuristic"
    n_updated <- n_updated + 1L
  }
  cat(sprintf("  Updated %d rows\n", n_updated))

  # Write back
  removeWorksheet(wb, "Datacenters")
  addWorksheet(wb, "Datacenters", tabColour = "#004E60")
  writeData(wb, "Datacenters", atlas, na.string = "")
  hdr <- createStyle(fontColour = "#FFFFFF", fgFill = "#1F4E79",
                     textDecoration = "Bold", border = "Bottom")
  addStyle(wb, "Datacenters", hdr, rows = 1,
           cols = seq_len(ncol(atlas)), gridExpand = TRUE)
  freezePane(wb, "Datacenters", firstRow = TRUE)
  addFilter(wb,  "Datacenters", row = 1, cols = seq_len(ncol(atlas)))
  saveWorkbook(wb, xlsx_path, overwrite = TRUE)
  cat(sprintf("  Saved: %s\n", xlsx_path))
  invisible(atlas)
}

# Run the merge
merge_phase4_into_excel()

# ══════════════════════════════════════════════════════════════════════════════
# 8. SUMMARY BY STATE
# ══════════════════════════════════════════════════════════════════════════════
cat("\n--- Phase 4 summary by state (top 15) ---\n")
echo_phase4_out |>
  summarise(
    facilities    = n(),
    total_mw_est  = sum(phase4_mw_est, na.rm = TRUE),
    major_count   = sum(permit_tier == "major", na.rm = TRUE),
    synth80_count = sum(permit_tier == "synthetic_minor_80pct", na.rm = TRUE),
    .by = state
  ) |>
  arrange(desc(total_mw_est)) |>
  slice_head(n = 15) |>
  print()

cat("\n--- Hyperscaler facilities with highest estimates ---\n")
echo_phase4_out |>
  filter(!is.na(echo_operator)) |>
  arrange(desc(phase4_mw_est)) |>
  select(echo_name, state, permit_tier, iad_building_count,
         phase4_mw_est, air_permit_ids) |>
  slice_head(n = 20) |>
  print(width = 120)
