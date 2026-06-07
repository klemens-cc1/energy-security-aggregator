phase2 = r"""

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
    rep("hyperscaler",6), rep("major_colo",17), rep("regional_colo",14),
    rep("specialty",2), rep("crypto_miner",4), rep("major_colo",3), rep("telco_pop",6)
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

atlas_out <- plyr::rbind.fill(atlas_out, echo_append)
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
"""

with open('datacenter_merge.R', 'a', encoding='utf-8') as f:
    f.write(phase2)
print('Done — Phase 2 appended to datacenter_merge.R')
