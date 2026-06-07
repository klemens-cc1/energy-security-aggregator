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


# ══════════════════════════════════════════════════════════════════════════════
# PHASE 2 — OPERATOR BRACKETS + EPA ECHO ENRICHMENT
# ══════════════════════════════════════════════════════════════════════════════

# ── State normalisation ────────────────────────────────────────────────────────
full_to_abbrev <- c(
  "DISTRICT OF COLUMBIA"="DC","ILLINOIS"="IL","TEXAS"="TX","NEW YORK"="NY",
  "CALIFORNIA"="CA","VIRGINIA"="VA","GEORGIA"="GA","ARIZONA"="AZ",
  "NORTH CAROLINA"="NC","COLORADO"="CO","MINNESOTA"="MN","MASSACHUSETTS"="MA",
  "NEW JERSEY"="NJ","WASHINGTON"="WA","CONNECTICUT"="CT","NEBRASKA"="NE",
  "OREGON"="OR"
)
atlas_out$state_clean <- toupper(trimws(as.character(atlas_out[[atlas_state_col]])))
atlas_out$state_clean <- ifelse(atlas_out$state_clean %in% names(full_to_abbrev),
                                full_to_abbrev[atlas_out$state_clean],
                                atlas_out$state_clean)

# ── Source confidence column ───────────────────────────────────────────────────
atlas_out$source_confidence <- atlas_out$match_status
atlas_out$source_confidence[is.na(atlas_out$source_confidence)] <- "no_match"

# ── Core Scientific exact MW from SEC 10-K (FY2025) ───────────────────────────
core_lookup <- list(
  "Denton 1"    = list(mw=394,  utility="Denton Municipal Utilities"),
  "Cottonwood"  = list(mw=300,  utility="Texas New Mexico Power (TNMP)"),
  "Austin 1"    = list(mw=20,   utility=NA_character_),
  "Calvert"     = list(mw=150,  utility="Tennessee Valley Authority (TVA)"),
  "Marble"      = list(mw=117,  utility="Duke Energy / Murphy Electric"),
  "Grand Forks" = list(mw=100,  utility="Nodak Electric Cooperative"),
  "Muskogee"    = list(mw=100,  utility="Oklahoma Gas & Electric (OG&E)"),
  "Auburn"      = list(mw=50,   utility="Alabama Power (Southern Company)"),
  "Dalton"      = list(mw=NA,   utility=NA_character_)
)
core_rows <- grepl("Core Scientific", atlas_out$Company, ignore.case=TRUE)
for (key in names(core_lookup)) {
  hits <- core_rows & grepl(key, atlas_out[[atlas_name_col]], ignore.case=TRUE)
  if (any(hits)) {
    e <- core_lookup[[key]]
    atlas_out$est_power_kw[hits]      <- if (!is.na(e$mw)) e$mw * 1000 else NA_real_
    atlas_out$primary_utility[hits]   <- if (!is.na(e$utility)) e$utility else atlas_out$primary_utility[hits]
    atlas_out$source_confidence[hits] <- if (!is.na(e$mw)) "sec_filing" else "not_in_filing"
  }
}

# ── Digital Realty metro averages (1Q26 supplement) ───────────────────────────
dlr_metro_mw <- c(DC=25.5, VA=25.5, IL=17.7, TX=6.2, NY=6.7, CA=6.5)
dlr_rows <- grepl("Digital Realty", atlas_out$Company, ignore.case=TRUE)
dlr_mw   <- ifelse(atlas_out$state_clean[dlr_rows] %in% names(dlr_metro_mw),
                   dlr_metro_mw[atlas_out$state_clean[dlr_rows]], 11.2)
atlas_out$est_power_kw[dlr_rows]      <- dlr_mw * 1000
atlas_out$source_confidence[dlr_rows] <- "investor_supplement_metro_avg"

# ── Iron Mountain portfolio average (488 MW / 31 sites) ───────────────────────
irm_rows <- grepl("Iron Mountain", atlas_out$Company, ignore.case=TRUE)
atlas_out$est_power_kw[irm_rows]      <- 15.7 * 1000
atlas_out$source_confidence[irm_rows] <- "investor_supplement_portfolio_avg"

supp_rows <- atlas_out$source_confidence %in% c(
  "sec_filing","investor_supplement_metro_avg","investor_supplement_portfolio_avg")
atlas_out$est_annual_cost_musd[supp_rows] <- round(
  atlas_out$est_power_kw[supp_rows] * HOURS_PER_YEAR *
  (atlas_out$commercial_rate_cents_kwh[supp_rows] / 100) / 1e6, 3)

# ── Operator bracket table ─────────────────────────────────────────────────────
op_brackets <- data.frame(
  pattern = c(
    "^Amazon$","^Google$","^Microsoft$","^Meta$","^Facebook$","^Apple$",
    "Equinix","CyrusOne","QTS|Quality Technology Services",
    "EdgeConneX","Vantage Data","CoreSite","Stack Infrastructure",
    "Aligned","Switch","Compass Datacenter","PowerHouse","CloudHQ",
    "T5 Data","Brookfield Infrastructure","Carter Validus","Mapletree","Tract",
    "DataBank","Stream Data","Flexential","Tierpoint|TierPoint","Cologix",
    "Centersquare|Evoque","Colocation America","Prime Data","Cyxtera","NTT",
    "INAP|Internap","DC Blox","vXchnge","ColoSpace","Expedient","H5 Data",
    "365 Data","Zenlayer","Cielo Digital","FirstLight","Sungard","CBTS",
    "TeraWulf","Applied Digital","Crusoe","Soluna","EdgeCore","Sabey","Prologis",
    "CenturyLink|Lumen","XO Communications","Zayo","Cogent","Windstream","Crown Castle"
  ),
  avg_mw = c(
    150,50,75,80,80,150,
    15,45,75,30,80,25,80,50,100,50,80,30,40,40,20,50,50,
    8,40,15,10,15,15,10,35,20,35,10,10,8,8,10,15,8,5,20,5,10,4,
    75,100,20,20,50,30,50,
    3,2,2,1,2,1
  ),
  tier = c(
    rep("hyperscaler",6), rep("major_colo",17), rep("regional_colo",22),
    rep("crypto_miner",4), rep("major_colo",3), rep("telco_pop",6)
  ),
  stringsAsFactors = FALSE
)

no_match_flag <- atlas_out$source_confidence == "no_match"
for (i in seq_len(nrow(op_brackets))) {
  hits <- no_match_flag & grepl(op_brackets$pattern[i], atlas_out$Company,
                                ignore.case=TRUE, perl=TRUE)
  if (any(hits)) {
    atlas_out$est_power_kw[hits]      <- op_brackets$avg_mw[i] * 1000
    atlas_out$source_confidence[hits] <- paste0("operator_bracket_", op_brackets$tier[i])
    no_match_flag[hits]               <- FALSE
  }
}
atlas_out$est_power_kw[no_match_flag]      <- 5 * 1000
atlas_out$source_confidence[no_match_flag] <- "operator_bracket_unknown"

bracket_rows <- grepl("operator_bracket", atlas_out$source_confidence)
atlas_out$est_annual_cost_musd[bracket_rows] <- round(
  atlas_out$est_power_kw[bracket_rows] * HOURS_PER_YEAR *
  (atlas_out$commercial_rate_cents_kwh[bracket_rows] / 100) / 1e6, 3)

# ══════════════════════════════════════════════════════════════════════════════
# EPA ECHO NAICS 518210 ENRICHMENT
# Source: https://echo.epa.gov/files/echodownloads/echo_exporter.zip
# ══════════════════════════════════════════════════════════════════════════════

ECHO_URL <- "https://echo.epa.gov/files/echodownloads/echo_exporter.zip"
ECHO_DIR <- file.path(dirname(OUTPUT_PATH), "echo_tmp")
ECHO_ZIP <- file.path(ECHO_DIR, "echo_exporter.zip")
ECHO_CSV <- file.path(ECHO_DIR, "ECHO_EXPORTER.csv")

if (!dir.exists(ECHO_DIR)) dir.create(ECHO_DIR, recursive=TRUE)
if (!file.exists(ECHO_ZIP)) {
  cat("Downloading EPA ECHO Exporter (~392 MB)...\n")
  download.file(ECHO_URL, ECHO_ZIP, mode="wb", quiet=FALSE)
}
if (!file.exists(ECHO_CSV)) unzip(ECHO_ZIP, exdir=ECHO_DIR, overwrite=TRUE)

cat("Scanning ECHO for NAICS 518210 facilities...\n")
con <- file(ECHO_CSV, "r")
echo_header  <- readLines(con, n=1)
matched_lines <- character(0)
chunk_size <- 50000; total_read <- 0
repeat {
  chunk <- readLines(con, n=chunk_size)
  if (length(chunk) == 0) break
  total_read <- total_read + length(chunk)
  hits <- chunk[grepl("518210", chunk, fixed=TRUE)]
  if (length(hits) > 0) matched_lines <- c(matched_lines, hits)
}
close(con)
cat(sprintf("Found %d NAICS 518210 facilities\n", length(matched_lines)))

echo_dc <- read.csv(text=c(echo_header, matched_lines), stringsAsFactors=FALSE)
valid_states <- c("AL","AK","AZ","AR","CA","CO","CT","DE","FL","GA","HI","ID",
  "IL","IN","IA","KS","KY","LA","ME","MD","MA","MI","MN","MS","MO","MT",
  "NE","NV","NH","NJ","NM","NY","NC","ND","OH","OK","OR","PA","RI","SC",
  "SD","TN","TX","UT","VT","VA","WA","WV","WI","WY","DC")
echo_us <- echo_dc[echo_dc$FAC_STATE %in% valid_states &
  !is.na(echo_dc$FAC_LAT) & echo_dc$FAC_LAT != 0 &
  !is.na(echo_dc$FAC_LONG) & echo_dc$FAC_LONG != 0, ]

# Spatial join: nearest Atlas row within 500 m
atlas_lat <- as.numeric(atlas_out$Latitude)
atlas_lon <- as.numeric(atlas_out$Longitude)
echo_lat  <- as.numeric(echo_us$FAC_LAT)
echo_lon  <- as.numeric(echo_us$FAC_LONG)
match_idx <- integer(nrow(echo_us)); match_km <- numeric(nrow(echo_us))
for (i in seq_len(nrow(echo_us))) {
  dlat <- (atlas_lat - echo_lat[i]) * 111.0
  dlon <- (atlas_lon - echo_lon[i]) * 111.0 * cos(echo_lat[i] * pi/180)
  d    <- sqrt(dlat^2 + dlon^2)
  best <- which.min(d); match_idx[i] <- best; match_km[i] <- d[best]
}
echo_us$atlas_matched   <- match_km <= 0.5
echo_us$atlas_match_idx <- match_idx

atlas_out$echo_verified   <- FALSE
atlas_out$echo_npdes_flag <- FALSE
atlas_out$echo_air_flag   <- FALSE
m_e <- echo_us[echo_us$atlas_matched, ]
atlas_out$echo_verified[m_e$atlas_match_idx]   <- TRUE
atlas_out$echo_npdes_flag[m_e$atlas_match_idx] <- m_e$NPDES_FLAG == "Y"
atlas_out$echo_air_flag[m_e$atlas_match_idx]   <- m_e$AIR_FLAG   == "Y"

extract_operator <- function(name) {
  n <- toupper(trimws(name))
  ops <- list(
    c("AMAZON|AWS","Amazon"),      c("MICROSOFT","Microsoft"),
    c("GOOGLE","Google"),           c("META|FACEBOOK","Meta"),
    c("APPLE","Apple"),             c("CYRUSONE","CyrusOne"),
    c("EQUINIX","Equinix"),         c("DIGITAL REALTY","Digital Realty Trust"),
    c("NTT","NTT"),                 c("IRON MOUNTAIN","Iron Mountain"),
    c("STACK INFRA","Stack Infrastructure"),
    c("VANTAGE","Vantage Data Centers"),
    c("EDGECORE","EdgeCore"),       c("CORESITE","CoreSite"),
    c("QTS","QTS"),                 c("DATABANK","DataBank"),
    c("FLEXENTIAL","Flexential"),   c("TIERPOINT","TierPoint"),
    c("COLOGIX","Cologix"),         c("ALIGNED","Aligned"),
    c("COMPASS","Compass Datacenters"),
    c("CRUSOE","Crusoe"),           c("APPLIED DIGITAL","Applied Digital"),
    c("TERAWULF","TeraWulf"),       c("STREAM DATA","Stream Data Centers"),
    c("SABEY","Sabey"),             c("EDGECONNEX|EDGECONEX","EdgeConneX"),
    c("SWITCH","Switch"),           c("CENTURYLINK|LUMEN","CenturyLink"),
    c("COGENT","Cogent")
  )
  for (o in ops) if (grepl(o[1], n)) return(o[2])
  return(NA_character_)
}

mw_by_op <- c(Amazon=150,Microsoft=75,Google=50,Meta=80,Apple=150,
  Equinix=15,CyrusOne=45,QTS=75,NTT=35,
  "Vantage Data Centers"=80,"Stack Infrastructure"=80,
  Aligned=50,CoreSite=25,EdgeConneX=30,
  "Compass Datacenters"=50,Switch=100,TierPoint=10,Cogent=1,Crusoe=20,
  Sabey=30,"Digital Realty Trust"=25,"Iron Mountain"=15.7,
  "Stream Data Centers"=40,EdgeCore=50,DataBank=8,Flexential=15)

unmatched        <- echo_us[!echo_us$atlas_matched, ]
unmatched$operator <- sapply(unmatched$FAC_NAME, extract_operator)
echo_new         <- unmatched[!is.na(unmatched$operator), ]
echo_new$state_clean <- toupper(trimws(echo_new$FAC_STATE))
echo_new$state_clean <- ifelse(echo_new$state_clean %in% names(full_to_abbrev),
                               full_to_abbrev[echo_new$state_clean],
                               echo_new$state_clean)
mw_v   <- mw_by_op[echo_new$operator]; mw_v[is.na(mw_v)] <- 5
rate_v <- commercial_rate_by_state[echo_new$state_clean]

echo_append <- data.frame(
  Name=echo_new$FAC_NAME, Company=echo_new$operator,
  City=echo_new$FAC_CITY, State=echo_new$state_clean,
  Address=echo_new$FAC_STREET,
  Latitude=as.numeric(echo_new$FAC_LAT), Longitude=as.numeric(echo_new$FAC_LONG),
  est_power_kw=mw_v*1000,
  est_annual_cost_musd=round(mw_v*1000*HOURS_PER_YEAR*(rate_v/100)/1e6, 3),
  source_confidence="echo_operator_bracket",
  primary_utility=primary_utility_by_state[echo_new$state_clean],
  commercial_rate_cents_kwh=rate_v,
  eia_grid_region=eia_region_by_state[echo_new$state_clean],
  eia_rto=rto_by_region[eia_region_by_state[echo_new$state_clean]],
  echo_verified=TRUE,
  echo_npdes_flag=echo_new$NPDES_FLAG=="Y",
  echo_air_flag=echo_new$AIR_FLAG=="Y",
  stringsAsFactors=FALSE, row.names=NULL
)

rbind_fill <- function(a, b) {
  for (col in setdiff(names(b), names(a))) a[[col]] <- NA
  for (col in setdiff(names(a), names(b))) b[[col]] <- NA
  rbind(a[, union(names(a), names(b))], b[, union(names(a), names(b))])
}
atlas_out <- rbind_fill(atlas_out, echo_append)
cat(sprintf("Total rows after ECHO append: %d\n", nrow(atlas_out)))
cat(sprintf("Echo-verified rows: %d | New rows added: %d\n",
            sum(atlas_out$echo_verified, na.rm=TRUE), nrow(echo_append)))

# ══════════════════════════════════════════════════════════════════════════════
# FINAL OUTPUT
# ══════════════════════════════════════════════════════════════════════════════

FINAL_PATH <- sub("\\.xlsx$", "_final.xlsx", OUTPUT_PATH)
keep <- intersect(c("Name","Company","City","State","Address","Latitude","Longitude",
  "es_facility_name","es_floor_space_sqft","match_score","est_power_kw",
  "est_annual_cost_musd","source_confidence","primary_utility",
  "commercial_rate_cents_kwh","eia_grid_region","eia_rto",
  "echo_verified","echo_npdes_flag","echo_air_flag"), names(atlas_out))
final_out <- atlas_out[, keep]

conf_ref <- data.frame(
  source_confidence=c("sec_filing","exact","fuzzy",
    "investor_supplement_metro_avg","investor_supplement_portfolio_avg",
    "operator_bracket_hyperscaler","operator_bracket_crypto_miner",
    "operator_bracket_major_colo","operator_bracket_regional_colo",
    "operator_bracket_specialty","operator_bracket_telco_pop",
    "operator_bracket_property_manager","operator_bracket_unknown",
    "echo_operator_bracket","not_in_filing"),
  description=c(
    "Exact MW from SEC 10-K filing (Core Scientific FY2025)",
    "ENERGY STAR exact name match - floor space proxy",
    "ENERGY STAR fuzzy name match - floor space proxy",
    "Digital Realty metro MW / site count (1Q26 supplement)",
    "Iron Mountain portfolio average (488 MW / 31 sites)",
    "Operator bracket - hyperscaler published US capacity estimate",
    "Operator bracket - public crypto miner estimate",
    "Operator bracket - major colo industry average",
    "Operator bracket - regional colo industry average",
    "Operator bracket - specialty operator estimate",
    "Operator bracket - telecom network PoP, low MW",
    "Operator bracket - property manager, not direct operator",
    "No operator data - generic 5 MW default",
    "EPA ECHO NAICS 518210 facility, operator bracket applied",
    "In Atlas but absent from most recent SEC filing, likely decommissioned"),
  stringsAsFactors=FALSE)

wb2  <- createWorkbook()
hdr2 <- createStyle(fontColour="#FFFFFF",fgFill="#1F4E79",
                    textDecoration="Bold",border="Bottom")
addWorksheet(wb2,"Datacenters")
writeData(wb2,"Datacenters",final_out,na.string="")
addStyle(wb2,"Datacenters",hdr2,rows=1,cols=seq_len(ncol(final_out)),gridExpand=TRUE)
freezePane(wb2,"Datacenters",firstRow=TRUE)
addFilter(wb2,"Datacenters",row=1,cols=seq_len(ncol(final_out)))
addWorksheet(wb2,"Confidence Reference")
writeData(wb2,"Confidence Reference",conf_ref,na.string="")
addStyle(wb2,"Confidence Reference",hdr2,rows=1,cols=1:2,gridExpand=TRUE)
freezePane(wb2,"Confidence Reference",firstRow=TRUE)
saveWorkbook(wb2, FINAL_PATH, overwrite=TRUE)
cat(sprintf("Final output: %s\n  Rows: %d | Columns: %d\n",
            FINAL_PATH, nrow(final_out), ncol(final_out)))

# ==============================================================================
# PHASE 3: CAMPUS CLUSTERING
# Same-operator buildings within CAMPUS_DIST_M metres are treated as one campus.
# Bracket MW is split among buildings so the campus total equals one bracket unit.
# Only rows with operator_bracket_* or echo_operator_bracket confidence are
# clustered; sec_filing / exact / fuzzy / investor_supplement are per-building.
# ==============================================================================
cat("\n--- Phase 3: Campus Clustering ---\n")

CLUSTER_TIERS <- c(
  "operator_bracket_hyperscaler", "operator_bracket_major_colo",
  "operator_bracket_regional_colo", "operator_bracket_specialty",
  "operator_bracket_telco_pop",    "operator_bracket_crypto_miner",
  "operator_bracket_unknown",      "echo_operator_bracket"
)
CAMPUS_DIST_M <- 1000   # metres; 1 km covers spread hyperscaler campuses

# BFS connected-components for n nodes with an edge matrix (2-col, i < j)
bfs_components <- function(n, edge_mat) {
  adj <- vector("list", n)
  if (!is.null(edge_mat) && nrow(edge_mat) > 0) {
    for (k in seq_len(nrow(edge_mat))) {
      i <- edge_mat[k, 1]; j <- edge_mat[k, 2]
      adj[[i]] <- c(adj[[i]], j)
      adj[[j]] <- c(adj[[j]], i)
    }
  }
  labels <- integer(n); comp <- 0L
  for (s in seq_len(n)) {
    if (labels[s] != 0L) next
    comp <- comp + 1L; q <- s; labels[s] <- comp
    while (length(q) > 0) {
      curr <- q[1]; q <- q[-1]
      for (nb in adj[[curr]]) {
        if (labels[nb] == 0L) { labels[nb] <- comp; q <- c(q, nb) }
      }
    }
  }
  labels
}

flat_dist_m <- function(lat1, lon1, lat2, lon2) {
  dlat <- (lat2 - lat1) * 111000
  dlon <- (lon2 - lon1) * 111000 * cos((lat1 + lat2) / 2 * pi / 180)
  sqrt(dlat^2 + dlon^2)
}

atlas_out$campus_id             <- NA_character_
atlas_out$campus_building_count <- 1L
atlas_out$campus_alloc_method   <- "single"

lat_num <- suppressWarnings(as.numeric(atlas_out$Latitude))
lon_num <- suppressWarnings(as.numeric(atlas_out$Longitude))

clust_idx <- which(
  atlas_out$source_confidence %in% CLUSTER_TIERS &
  !is.na(lat_num) & !is.na(lon_num)
)

companies <- unique(atlas_out$Company[clust_idx])
companies <- companies[!is.na(companies)]

campus_n    <- 0L
rows_merged <- 0L

for (co in companies) {
  idx  <- clust_idx[which(atlas_out$Company[clust_idx] == co)]
  n    <- length(idx)
  lats <- lat_num[idx]
  lons <- lon_num[idx]

  edge_mat <- NULL
  if (n >= 2) {
    for (i in seq_len(n - 1)) {
      for (j in (i + 1):n) {
        if (flat_dist_m(lats[i], lons[i], lats[j], lons[j]) <= CAMPUS_DIST_M) {
          edge_mat <- rbind(edge_mat, c(i, j))
        }
      }
    }
  }

  labels <- bfs_components(n, edge_mat)

  for (comp in unique(labels)) {
    members    <- which(labels == comp)
    global_idx <- idx[members]
    n_bldg     <- length(members)
    campus_n   <- campus_n + 1L
    cid        <- sprintf("CAMPUS_%05d", campus_n)

    atlas_out$campus_id[global_idx]             <- cid
    atlas_out$campus_building_count[global_idx] <- n_bldg

    if (n_bldg > 1) {
      rows_merged <- rows_merged + n_bldg
      bracket_kw  <- max(atlas_out$est_power_kw[global_idx], na.rm = TRUE)
      sqft        <- atlas_out$es_floor_space_sqft[global_idx]
      has_sqft    <- !is.na(sqft) & sqft > 0

      if (all(has_sqft)) {
        share <- sqft / sum(sqft)
        atlas_out$est_power_kw[global_idx]        <- round(bracket_kw * share, 1)
        atlas_out$campus_alloc_method[global_idx] <- "floor_space_weighted"
      } else {
        atlas_out$est_power_kw[global_idx]        <- round(bracket_kw / n_bldg, 1)
        atlas_out$campus_alloc_method[global_idx] <- "even_split"
      }
    }
  }
}

# Assign solo campus IDs to all remaining rows
remaining <- which(is.na(atlas_out$campus_id))
for (i in remaining) {
  campus_n <- campus_n + 1L
  atlas_out$campus_id[i] <- sprintf("CAMPUS_%05d", campus_n)
}

# Recompute annual cost with adjusted power
atlas_out$est_annual_cost_musd <- round(
  atlas_out$est_power_kw * HOURS_PER_YEAR *
    (atlas_out$commercial_rate_cents_kwh / 100) / 1e6, 3
)

cat(sprintf("Rows in clustering tiers:    %d\n", length(clust_idx)))
cat(sprintf("Multi-building campus rows:  %d\n", rows_merged))
cat(sprintf("Total campus IDs assigned:   %d\n", campus_n))
cat(sprintf("Est total power after clust: %.1f GW\n",
            sum(atlas_out$est_power_kw, na.rm = TRUE) / 1e6))

# ==============================================================================
# RE-SAVE WITH CAMPUS COLUMNS
# ==============================================================================
keep3 <- intersect(
  c("Name","Company","City","State","Address","Latitude","Longitude",
    "es_facility_name","es_floor_space_sqft","match_score",
    "est_power_kw","est_annual_cost_musd","source_confidence",
    "primary_utility","commercial_rate_cents_kwh","eia_grid_region","eia_rto",
    "echo_verified","echo_npdes_flag","echo_air_flag",
    "campus_id","campus_building_count","campus_alloc_method"),
  names(atlas_out)
)
final_out3 <- atlas_out[, keep3]

wb3 <- createWorkbook()
addWorksheet(wb3, "Datacenters")
writeData(wb3, "Datacenters", final_out3, na.string = "")
addStyle(wb3, "Datacenters", hdr2, rows=1, cols=seq_len(ncol(final_out3)), gridExpand=TRUE)
freezePane(wb3, "Datacenters", firstRow=TRUE)
addFilter(wb3, "Datacenters", row=1, cols=seq_len(ncol(final_out3)))

addWorksheet(wb3, "Confidence Reference")
writeData(wb3, "Confidence Reference", conf_ref, na.string = "")
addStyle(wb3, "Confidence Reference", hdr2, rows=1, cols=1:2, gridExpand=TRUE)
freezePane(wb3, "Confidence Reference", firstRow=TRUE)

saveWorkbook(wb3, FINAL_PATH, overwrite = TRUE)
cat(sprintf("\nSaved (Phase 3): %s\n  Rows: %d | Columns: %d\n",
            FINAL_PATH, nrow(final_out3), ncol(final_out3)))
