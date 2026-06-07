# patch_operators.R — one-off ownership corrections
library(openxlsx)

FINAL_PATH <- "datacenter_merged_final.xlsx"

wb <- loadWorkbook(FINAL_PATH)
df <- readWorkbook(wb, sheet = "Datacenters")
cat(sprintf("Loaded %d rows\n", nrow(df)))

# Sila (formerly Carter Validus) sold all 29 US DCs to Mapletree in 2021
# Source: DCD May 20 2021 — https://www.datacenterdynamics.com/en/news/sila-previously-carter-validus-sells-all-its-data-centers-for-13bn/
idx <- grepl("carter validus", df$Company, ignore.case = TRUE)
cat(sprintf("Carter Validus → Mapletree Investments: %d rows\n", sum(idx)))
df$Company[idx] <- "Mapletree Investments"

# Write back to existing Datacenters sheet (row 1 = header)
writeData(wb, "Datacenters", df, startRow = 1, startCol = 1, na.string = "")

saveWorkbook(wb, FINAL_PATH, overwrite = TRUE)
cat("Saved.\n")
