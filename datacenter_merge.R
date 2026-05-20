# datacenter_merge.R
# Layers:
#   1. Global Data Center Atlas  (lat/lon, operator, address)
#   2. EPA ENERGY STAR           (floor space, certifications → power estimate)
#   3. EIA-861 2023              (primary utility, commercial rate, annual cost)
#   4. EIA grid region / RTO     (WECC, PJM, MISO, ERCOT …)
#
# Install once:
#   install.packages(c("readxl", "openxlsx", "stringdist"))

library(readxl)
library(openxlsx)
library(stringdist)

# ── Paths ──────────────────────────────────────────────────────────────────────
ATLAS_PATH      <- "C:/Users/wells/Downloads/datacenters.xlsx"
ENERGYSTAR_PATH <- "C:/Users/wells/VSprojects26/energy-security-aggregator/energystar_certified_datacenters.xlsx"
OUTPUT_PATH     <- "C:/Users/wells/VSprojects26/energy-security-aggregator/datacenter_merged.xlsx"
EIA861_DIR      <- "C:/Users/wells/VSprojects26/energy-security-aggregator/eia861_tmp"

# ── Thresholds ─────────────────────────────────────────────────────────────────
MATCH_THRESHOLD <- 90       # ENERGY STAR fuzzy match cutoff

# ── Power density assumption ───────────────────────────────────────────────────
# ENERGY STAR certified sites: PUE ~1.3, IT density ~100 W/sq ft → 130 W/sq ft total
W_PER_SQFT      <- 130
HOURS_PER_YEAR  <- 8760

# ══════════════════════════════════════════════════════════════════════════════
# EIA-861 2023 DATA TABLES
# Source: EIA Form EIA-861 Annual Electric Power Industry Report (2023)
#         https://www.eia.gov/electricity/data/eia861/
# Commercial rates: EIA Electric Power Monthly Table 5.3 (2023 annual avg)
# Primary utility: largest IOU by commercial revenue per state
# ══════════════════════════════════════════════════════════════════════════════

# 2023 average commercial electricity rate (cents per kWh)
commercial_rate_by_state <- c(
  AK=22.5, AL=12.0, AR=10.5, AZ=12.8, CA=26.0, CO=12.5, CT=24.0, DC=14.5,
  DE=14.0, FL=12.5, GA=11.5, HI=38.0, IA=10.5, ID= 9.5, IL=12.5, IN=11.0,
  KS=11.0, KY= 9.5, LA=10.5, MA=24.0, MD=14.5, ME=20.0, MI=13.5, MN=12.0,
  MO=10.5, MS=11.5, MT=11.5, NC=11.5, ND=11.0, NE=10.5, NH=23.0, NJ=16.5,
  NM=12.5, NV=14.0, NY=18.5, OH=12.0, OK=10.5, OR=11.5, PA=13.5, RI=22.5,
  SC=11.0, SD=11.5, TN=11.0, TX=11.5, UT=10.5, VA=12.5, VT=18.0, WA= 9.0,
  WI=13.0, WV=11.0, WY=10.5
)

# Primary investor-owned utility (IOU) by state — largest by commercial revenue
primary_utility_by_state <- c(
  AK="Chugach Electric Association",
  AL="Alabama Power (Southern Company)",
  AR="Entergy Arkansas",
  AZ="Arizona Public Service (APS)",
  CA="Pacific Gas & Electric (PG&E)",
  CO="Xcel Energy (Public Service Co. of Colorado)",
  CT="Eversource Energy",
  DC="Pepco (Exelon)",
  DE="Delmarva Power (Exelon)",
  FL="Florida Power & Light (NextEra Energy)",
  GA="Georgia Power (Southern Company)",
  HI="Hawaiian Electric (HECO)",
  IA="MidAmerican Energy (Berkshire Hathaway)",
  ID="Idaho Power",
  IL="ComEd (Exelon)",
  IN="Duke Energy Indiana",
  KS="Evergy",
  KY="LG&E and KU Energy (PPL Corporation)",
  LA="Entergy Louisiana",
  MA="Eversource Energy",
  MD="Baltimore Gas & Electric (BGE / Exelon)",
  ME="Central Maine Power (Avangrid)",
  MI="DTE Energy / Consumers Energy",
  MN="Xcel Energy (Northern States Power)",
  MO="Ameren Missouri",
  MS="Entergy Mississippi",
  MT="NorthWestern Energy",
  NC="Duke Energy Carolinas / Duke Energy Progress",
  ND="Xcel Energy (Northern States Power)",
  NE="Omaha Public Power District (OPPD)",
  NH="Eversource Energy",
  NJ="PSEG (Public Service Electric & Gas)",
  NM="PNM (Public Service Company of New Mexico)",
  NV="NV Energy (Berkshire Hathaway)",
  NY="Con Edison / National Grid",
  OH="FirstEnergy / AEP Ohio",
  OK="Oklahoma Gas & Electric (OG&E)",
  OR="Portland General Electric",
  PA="PECO (Exelon) / PPL Electric Utilities",
  RI="National Grid",
  SC="Duke Energy Carolinas / Dominion Energy SC",
  SD="Xcel Energy (Northern States Power)",
  TN="Tennessee Valley Authority (TVA)",
  TX="Oncor Electric Delivery / CenterPoint Energy",
  UT="Rocky Mountain Power (PacifiCorp)",
  VA="Dominion Energy Virginia",
  VT="Green Mountain Power",
  WA="Puget Sound Energy / Pacific Power",
  WI="We Energies / Alliant Energy",
  WV="Appalachian Power (AEP)",
  WY="Rocky Mountain Power (PacifiCorp)"
)

# EIA reliability region by state
eia_region_by_state <- c(
  AK="Alaska", AL="SERC", AR="MISO", AZ="WECC", CA="WECC", CO="WECC",
  CT="NPCC",   DC="PJM",  DE="PJM",  FL="SERC", GA="SERC", HI="Hawaii",
  IA="MISO",   ID="WECC", IL="MISO", IN="MISO", KS="SPP",  KY="SERC",
  LA="SERC",   MA="NPCC", MD="PJM",  ME="NPCC", MI="MISO", MN="MISO",
  MO="MISO",   MS="SERC", MT="WECC", NC="SERC", ND="MISO", NE="SPP",
  NH="NPCC",   NJ="PJM",  NM="WECC", NV="WECC", NY="NPCC", OH="PJM",
  OK="SPP",    OR="WECC", PA="PJM",  RI="NPCC", SC="SERC", SD="MISO",
  TN="SERC",   TX="ERCOT",UT="WECC", VA="PJM",  VT="NPCC", WA="WECC",
  WI="MISO",   WV="PJM",  WY="WECC"
)

# ISO/RTO operator by EIA region
rto_by_region <- c(
  WECC   = "WECC (CAISO / PacifiCorp / NV Energy / APS)",
  PJM    = "PJM Interconnection",
  MISO   = "Midcontinent ISO (MISO)",
  SERC   = "SERC Reliability / Southern Company / Duke / TVA",
  NPCC   = "NPCC (ISO-NE / NYISO)",
  SPP    = "Southwest Power Pool (SPP)",
  ERCOT  = "Electric Reliability Council of Texas (ERCOT)",
  Alaska = "Alaska Systems Coordinating Council",
  Hawaii = "Hawaiian Electric (HECO)"
)

# ══════════════════════════════════════════════════════════════════════════════
# OPTIONAL: Download EIA-861 Utility Data for richer utility detail
# Uncomment to enable — downloads ~15 MB zip from EIA
# ══════════════════════════════════════════════════════════════════════════════

fetch_eia861_utilities <- function(dir) {
  url     <- "https://www.eia.gov/electricity/data/eia861/archive/zip/f861_2023.zip"
  zipfile <- file.path(dir, "f861_2023.zip")

  if (!dir.exists(dir)) dir.create(dir, recursive=TRUE)
  if (!file.exists(zipfile)) {
    cat("Downloading EIA-861 2023...\n")
    tryCatch(
      download.file(url, zipfile, mode="wb", quiet=TRUE),
      error = function(e) { cat("  Download failed:", conditionMessage(e), "\n"); return(NULL) }
    )
  }
  if (!file.exists(zipfile)) return(NULL)

  files <- unzip(zipfile, list=TRUE)$Name
  util_file <- files[grepl("Utility_Data", files, ignore.case=TRUE)][1]
  if (is.na(util_file)) return(NULL)

  tmp <- unzip(zipfile, files=util_file, exdir=dir)
  tryCatch({
    df <- read_excel(tmp, skip=1)   # EIA-861 utility file has a 1-row title header
    cat(sprintf("  EIA-861 utility data loaded: %d utilities\n", nrow(df)))
    return(df)
  }, error=function(e) { cat("  Parse failed:", conditionMessage(e), "\n"); return(NULL) })
}

# Uncomment to download:
# eia861 <- fetch_eia861_utilities(EIA861_DIR)

# ══════════════════════════════════════════════════════════════════════════════
# STATE / NAME HELPERS
# ══════════════════════════════════════════════════════════════════════════════

state_to_abbrev <- c(
  "Alabama"="AL","Alaska"="AK","Arizona"="AZ","Arkansas"="AR","California"="CA",
  "Colorado"="CO","Connecticut"="CT","Delaware"="DE","Florida"="FL","Georgia"="GA",
  "Hawaii"="HI","Idaho"="ID","Illinois"="IL","Indiana"="IN","Iowa"="IA",
  "Kansas"="KS","Kentucky"="KY","Louisiana"="LA","Maine"="ME","Maryland"="MD",
  "Massachusetts"="MA","Michigan"="MI","Minnesota"="MN","Mississippi"="MS",
  "Missouri"="MO","Montana"="MT","Nebraska"="NE","Nevada"="NV",
  "New Hampshire"="NH","New Jersey"="NJ","New Mexico"="NM","New York"="NY",
  "North Carolina"="NC","North Dakota"="ND","Ohio"="OH","Oklahoma"="OK",
  "Oregon"="OR","Pennsylvania"="PA","Rhode Island"="RI","South Carolina"="SC",
  "South Dakota"="SD","Tennessee"="TN","Texas"="TX","Utah"="UT","Vermont"="VT",
  "Virginia"="VA","Washington"="WA","West Virginia"="WV","Wisconsin"="WI",
  "Wyoming"="WY","District of Columbia"="DC"
)
valid_abbrevs <- names(setNames(names(state_to_abbrev), state_to_abbrev))

normalise_state <- function(s) {
  s <- trimws(toupper(as.character(s)))
  if (s %in% valid_abbrevs) return(s)
  m <- state_to_abbrev[names(state_to_abbrev)[tolower(names(state_to_abbrev)) == tolower(s)]]
  if (length(m) > 0 && !is.na(m[1])) return(unname(m[1]))
  return(NA_character_)
}

STRIP_WORDS <- c("llc","inc","corp","co","ltd","lp","the","a","an",
                 "data","center","centre","datacenter","campus",
                 "facility","site","building","complex","solutions")

normalise_name <- function(x) {
  x <- tolower(trimws(as.character(x)))
  x <- gsub("[^a-z0-9 ]", " ", x)
  toks <- strsplit(x, "\\s+")[[1]]
  toks <- toks[!toks %in% STRIP_WORDS & nchar(toks) > 0]
  paste(sort(toks), collapse = " ")
}

fuzzy_score <- function(a, b) round(stringsim(a, b, method="jw", p=0.1) * 100, 1)

# ══════════════════════════════════════════════════════════════════════════════
# LOAD DATASETS
# ══════════════════════════════════════════════════════════════════════════════

cat("Loading ATLAS dataset...\n")
atlas_raw <- read_excel(ATLAS_PATH)
cat(sprintf("  %d rows | columns: %s\n\n", nrow(atlas_raw), paste(names(atlas_raw), collapse=", ")))

cat("Loading ENERGY STAR dataset...\n")
es_raw <- read_excel(ENERGYSTAR_PATH)
cat(sprintf("  %d rows\n\n", nrow(es_raw)))

find_col <- function(df, patterns) {
  for (p in patterns) {
    m <- grep(p, names(df), ignore.case=TRUE, value=TRUE)
    if (length(m) > 0) return(m[1])
  }
  stop(paste("Cannot find column:", paste(patterns, collapse=" / ")))
}

atlas_name_col  <- find_col(atlas_raw, c("^name$","facility","site","name"))
atlas_state_col <- find_col(atlas_raw, c("^state$","state"))
atlas_lat_col   <- find_col(atlas_raw, c("^lat$","latitude"))
atlas_lon_col   <- find_col(atlas_raw, c("^lon$","^lng$","longitude","lon"))

cat(sprintf("ATLAS columns: name='%s'  state='%s'  lat='%s'  lon='%s'\n\n",
            atlas_name_col, atlas_state_col, atlas_lat_col, atlas_lon_col))

atlas <- atlas_raw
atlas$.state_norm <- sapply(atlas[[atlas_state_col]], normalise_state)
atlas$.name_norm  <- sapply(atlas[[atlas_name_col]],  normalise_name)

n_raw <- nrow(atlas)
atlas <- atlas[!is.na(atlas$.state_norm), ]
cat(sprintf("ATLAS: %d US rows (dropped %d non-US)\n\n", nrow(atlas), n_raw - nrow(atlas)))

es <- es_raw
es$.state_norm <- sapply(es$State,           normalise_state)
es$.name_norm  <- sapply(es$`Facility Name`, normalise_name)

# ══════════════════════════════════════════════════════════════════════════════
# FUZZY MATCH: ATLAS ↔ ENERGY STAR
# ══════════════════════════════════════════════════════════════════════════════

cat(sprintf("Matching %d ATLAS rows against %d ENERGY STAR rows (threshold=%d)...\n",
            nrow(atlas), nrow(es), MATCH_THRESHOLD))

n <- nrow(atlas)
res_es_name <- rep("",       n)
res_owner   <- rep("",       n)
res_floor   <- rep(NA_real_, n)
res_year    <- rep(NA_real_, n)
res_labels  <- rep("",       n)
res_certs   <- rep("",       n)
res_score   <- rep(0,        n)
res_status  <- rep("no_match", n)

tick <- max(1L, n %/% 10L)

for (i in seq_len(n)) {
  if (i %% tick == 0) cat(sprintf("  %d%%\n", as.integer(i / n * 100)))

  aname  <- atlas$.name_norm[i]
  astate <- atlas$.state_norm[i]

  es_sub <- es[!is.na(es$.state_norm) & es$.state_norm == astate, ]
  if (nrow(es_sub) == 0) es_sub <- es

  scores     <- vapply(es_sub$.name_norm, function(nm) fuzzy_score(aname, nm), numeric(1))
  best_i     <- which.max(scores)
  best_score <- scores[best_i]

  if (best_score < MATCH_THRESHOLD) next

  best <- es_sub[best_i, ]
  res_es_name[i] <- as.character(best$`Facility Name`)
  res_owner[i]   <- as.character(best$Owner)
  res_floor[i]   <- suppressWarnings(as.numeric(best$`Total Floor Space`))
  res_year[i]    <- suppressWarnings(as.numeric(best$`Year Constructed`))
  res_labels[i]  <- as.character(best$`Label Years`)
  res_certs[i]   <- as.character(best$`Number of Certifications (Most Recent Year)`)
  res_score[i]   <- best_score
  res_status[i]  <- if (best_score == 100) "exact" else "fuzzy"
}
cat("  100%\n\nMatch complete.\n")

# ══════════════════════════════════════════════════════════════════════════════
# ASSEMBLE OUTPUT
# ══════════════════════════════════════════════════════════════════════════════

atlas_out <- atlas[, !grepl("^\\.", names(atlas))]
state_abbrev <- atlas$.state_norm   # carry forward for lookups

# ── ENERGY STAR columns ────────────────────────────────────────────────────────
atlas_out$es_facility_name      <- ifelse(res_es_name == "", NA, res_es_name)
atlas_out$es_owner              <- ifelse(res_owner   == "", NA, res_owner)
atlas_out$es_floor_space_sqft   <- res_floor
atlas_out$es_year_constructed   <- res_year
atlas_out$es_label_years        <- ifelse(res_labels == "", NA, res_labels)
atlas_out$es_num_certifications <- ifelse(res_certs  == "", NA, res_certs)
atlas_out$match_score           <- ifelse(res_score  == 0,  NA, res_score)
atlas_out$match_status          <- res_status

# ── Power estimate (ENERGY STAR matched rows only) ────────────────────────────
atlas_out$est_power_kw <- ifelse(
  !is.na(res_floor),
  round(res_floor * W_PER_SQFT / 1000, 0),
  NA_real_
)

# ── EIA-861 layer (all rows, state-level) ─────────────────────────────────────
atlas_out$eia_grid_region          <- eia_region_by_state[state_abbrev]
atlas_out$eia_rto                  <- rto_by_region[atlas_out$eia_grid_region]
atlas_out$primary_utility          <- primary_utility_by_state[state_abbrev]
atlas_out$commercial_rate_cents_kwh <- commercial_rate_by_state[state_abbrev]

# ── Annual cost estimate (where power kW is known) ────────────────────────────
# est_annual_cost_musd = est_power_kw × hours/yr × rate ($/kWh) / 1e6
atlas_out$est_annual_cost_musd <- ifelse(
  !is.na(atlas_out$est_power_kw) & !is.na(atlas_out$commercial_rate_cents_kwh),
  round(atlas_out$est_power_kw * HOURS_PER_YEAR *
        (atlas_out$commercial_rate_cents_kwh / 100) / 1e6, 3),
  NA_real_
)

# ── Summary ───────────────────────────────────────────────────────────────────
cat("\nMatch summary:\n")
print(table(atlas_out$match_status, useNA="ifany"))
cat(sprintf("\nRows with power estimate:    %d\n", sum(!is.na(atlas_out$est_power_kw))))
cat(sprintf("Rows with grid region:       %d\n",  sum(!is.na(atlas_out$eia_grid_region))))
cat(sprintf("Rows with primary utility:   %d\n",  sum(!is.na(atlas_out$primary_utility))))
cat(sprintf("Rows with cost estimate:     %d\n",  sum(!is.na(atlas_out$est_annual_cost_musd))))

matched_names <- unique(res_es_name[res_es_name != ""])
es_unmatched  <- es_raw[!as.character(es_raw$`Facility Name`) %in% matched_names, ]
cat(sprintf("Unmatched ENERGY STAR rows:  %d (Sheet 2)\n", nrow(es_unmatched)))

# ══════════════════════════════════════════════════════════════════════════════
# WRITE XLSX
# ══════════════════════════════════════════════════════════════════════════════

cat("\nWriting output...\n")
wb <- createWorkbook()

hdr <- createStyle(fontColour="#FFFFFF", fgFill="#1F4E79",
                   textDecoration="Bold", border="Bottom")
grn <- createStyle(fgFill="#E2EFDA")

# Sheet 1: full merged dataset
addWorksheet(wb, "Merged")
writeData(wb, "Merged", atlas_out, na.string="")
addStyle(wb, "Merged", hdr, rows=1, cols=seq_len(ncol(atlas_out)), gridExpand=TRUE)
exact_rows <- which(atlas_out$match_status == "exact") + 1L
if (length(exact_rows) > 0)
  addStyle(wb, "Merged", grn, rows=exact_rows, cols=seq_len(ncol(atlas_out)),
           gridExpand=TRUE, stack=TRUE)
freezePane(wb, "Merged", firstRow=TRUE)
addFilter(wb,  "Merged", row=1, cols=seq_len(ncol(atlas_out)))

# Sheet 2: unmatched ENERGY STAR (candidates to geocode and add)
addWorksheet(wb, "ES Unmatched")
writeData(wb, "ES Unmatched", es_unmatched, na.string="")
addStyle(wb, "ES Unmatched", hdr, rows=1, cols=seq_len(ncol(es_unmatched)), gridExpand=TRUE)
freezePane(wb, "ES Unmatched", firstRow=TRUE)

# Sheet 3: EIA reference table
eia_ref <- data.frame(
  state_abbrev          = names(commercial_rate_by_state),
  commercial_rate_cents_kwh = as.numeric(commercial_rate_by_state),
  primary_utility       = primary_utility_by_state[names(commercial_rate_by_state)],
  eia_grid_region       = eia_region_by_state[names(commercial_rate_by_state)],
  eia_rto               = rto_by_region[eia_region_by_state[names(commercial_rate_by_state)]],
  stringsAsFactors      = FALSE,
  row.names             = NULL
)
addWorksheet(wb, "EIA Reference")
writeData(wb, "EIA Reference", eia_ref, na.string="")
addStyle(wb, "EIA Reference", hdr, rows=1, cols=seq_len(ncol(eia_ref)), gridExpand=TRUE)
freezePane(wb, "EIA Reference", firstRow=TRUE)

saveWorkbook(wb, OUTPUT_PATH, overwrite=TRUE)

cat(sprintf("\nDone. Output: %s\n", OUTPUT_PATH))
cat(sprintf("  Sheet 1 'Merged':        %d rows, %d columns\n", nrow(atlas_out), ncol(atlas_out)))
cat(sprintf("  Sheet 2 'ES Unmatched':  %d rows\n", nrow(es_unmatched)))
cat(sprintf("  Sheet 3 'EIA Reference': %d states\n", nrow(eia_ref)))
cat("\nNew columns added to all rows:\n")
cat("  eia_grid_region           — WECC / PJM / MISO / SERC / ERCOT / NPCC / SPP\n")
cat("  eia_rto                   — ISO/RTO operator name\n")
cat("  primary_utility           — largest IOU by commercial revenue (EIA-861 2023)\n")
cat("  commercial_rate_cents_kwh — state avg commercial rate, cents/kWh (EIA 2023)\n")
cat("New columns added where ENERGY STAR match found:\n")
cat("  est_power_kw              — estimated total facility power draw\n")
cat("  est_annual_cost_musd      — estimated annual electricity cost (millions USD)\n")
