import os
import time
import logging
import httpx

log = logging.getLogger(__name__)

BASE_URL = "https://api.legiscan.com/"
MIN_INTERVAL = 1.1  # seconds between calls per LegiScan timing guidelines


class LegiScanClient:
    def __init__(self, api_key: str | None = None):
        self.api_key = api_key or os.environ.get("LEGISCAN_API_KEY")
        if not self.api_key:
            raise ValueError("LEGISCAN_API_KEY not set")
        self._last_call = 0.0

    def _get(self, op: str, **params) -> dict:
        elapsed = time.time() - self._last_call
        if elapsed < MIN_INTERVAL:
            time.sleep(MIN_INTERVAL - elapsed)

        try:
            resp = httpx.get(
                BASE_URL,
                params={"key": self.api_key, "op": op, **params},
                timeout=30,
            )
            resp.raise_for_status()
        finally:
            self._last_call = time.time()

        data = resp.json()
        if data.get("status") != "OK":
            raise RuntimeError(f"LegiScan {op} returned status={data.get('status')}: {data}")
        return data

    def get_dataset_list(self, state: str | None = None) -> list[dict]:
        kwargs = {"state": state} if state else {}
        return self._get("getDatasetList", **kwargs)["datasetlist"]

    def get_dataset(self, access_key: str, session_id: int) -> dict:
        return self._get("getDataset", id=session_id, access_key=access_key)["dataset"]

    def get_master_list_raw(self, state: str) -> dict:
        return self._get("getMasterListRaw", state=state)["masterlist"]

    def get_search(self, query: str, state: str, year: int = 2) -> list[dict]:
        """
        year: 1=all, 2=current, 3=recent (current+prior), 4=prior
        Returns list of result dicts with bill_id, relevance, change_hash, etc.
        """
        data = self._get("getSearch", query=query, state=state, year=year)
        results_raw = data.get("searchresult", {})
        return [v for k, v in results_raw.items() if k not in ("summary",)]

    def get_bill(self, bill_id: int) -> dict:
        return self._get("getBill", id=bill_id)["bill"]

    def get_bill_text(self, doc_id: int) -> dict:
        return self._get("getBillText", id=doc_id)["text"]
