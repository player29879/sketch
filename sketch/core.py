import datetime
import heapq
import logging
import sqlite3
import uuid

import pandas as pd
import requests

from .references import PandasDataframeColumn, Reference, SqliteColumn
from .sketches import SketchBase

# TODO: These object models are possibly different than the ones in api models
# and those are different than the ones in data models... need to rectify.
# either use a single source of truth, or have good robust tests.
# -- These feel more useful for the client, utility methods


class SketchPad:
    version = "0.0.1"
    sketches = SketchBase.all_sketches()

    def __init__(self, reference, context=None):
        self.version = "0.0.1"
        self.id = str(uuid.uuid4())
        self.metadata = {
            "id": self.id,
            "creation_start": datetime.datetime.utcnow().isoformat(),
        }
        self.reference = reference
        self.context = context or {}
        # TODO: consider alternate naming convention
        # so can do dictionary lookups
        self.sketches = []

    def get_sketch_by_name(self, name):
        sketches = [sk for sk in self.sketches if sk.name == name]
        if len(sketches) == 1:
            return sketches[0]
        return None

    def get_sketchdata_by_name(self, name):
        sketch = self.get_sketch_by_name(name)
        return sketch.data if sketch else None

    def minhash_jaccard(self, other):
        self_minhash = self.get_sketchdata_by_name("MinHash")
        other_minhash = other.get_sketchdata_by_name("MinHash")
        if self_minhash is None or other_minhash is None:
            return None
        return self_minhash.jaccard(other_minhash)

    def to_dict(self):
        return {
            "version": self.version,
            "metadata": self.metadata,
            "reference": self.reference.to_dict(),
            "sketches": [s.to_dict() for s in self.sketches],
            "context": self.context,
        }

    @classmethod
    def from_series(cls, series, reference):
        sp = cls(reference)
        for skcls in cls.sketches:
            sp.sketches.append(skcls.from_series(series))
        sp.metadata["creation_end"] = datetime.datetime.utcnow().isoformat()
        sp.context["column_name"] = series.name
        return sp

    @classmethod
    def from_dict(cls, data):
        assert data["version"] == cls.version
        sp = cls(Reference.from_dict(data["reference"]))
        sp.id = data["metadata"]["id"]
        sp.metadata = data["metadata"]
        sp.context = data["context"]
        sp.sketches = [SketchBase.from_dict(s) for s in data["sketches"]]
        return sp


# TODO: Add a "row-iterator" style, that builds sketchpads from a row-iterator


class Portfolio:
    def __init__(self, sketchpads=None):
        self.sketchpads = {sp.id: sp for sp in (sketchpads or [])}

    @classmethod
    def from_dataframe(cls, df):
        return cls().add_dataframe(df)

    def add_dataframe(self, df):
        for col in df.columns:
            sp = SketchPad.from_series(df[col])
            self.add_sketchpad(sp)
        return self

    def get_approx_pk_sketchpads(self):
        # is an estimated unique_key if unique count estimate
        # is > 97% the number of rows
        pf = Portfolio()
        for sketchpad in self.sketchpads.values():
            uq = sketchpad.get_sketchdata_by_name("HyperLogLog").count()
            rows = int(sketchpad.get_sketchdata_by_name("Rows"))
            if uq > 0.97 * rows:
                pf.add_sketchpad(sketchpad)
        return pf

    @classmethod
    def from_dataframes(cls, dfs):
        return cls().add_dataframes(dfs)

    def add_dataframes(self, dfs):
        for df in dfs:
            self.add_dataframe(df)
        return self

    @classmethod
    def from_sketchpad(cls, sketchpad):
        return cls().add_sketchpad(sketchpad)

    def add_sketchpad(self, sketchpad):
        self.sketchpads[sketchpad.id] = sketchpad
        return self

    @classmethod
    def from_sqlite(cls, sqlite_db_path):
        return cls().add_sqlite(sqlite_db_path)

    def add_sqlite(self, sqlite_db_path):
        conn = sqlite3.connect(sqlite_db_path)
        tables = pd.read_sql(
            "SELECT name FROM sqlite_schema WHERE type='table' ORDER BY name;", conn
        )
        logging.info(f"Found {len(tables)} tables in file {sqlite_db_path}")
        for i, table in enumerate(tables.name):
            df = pd.read_sql(f"SELECT * from '{table}'", conn)
            df.attrs |= {"table_name": table, "source": {"sqlite": sqlite_db_path}}
            self.add_dataframe(df)
        return self

    def closest_overlap(self, sketchpad, n=5):
        scores = []
        for sp in self.sketchpads.values():
            score = sketchpad.minhash_jaccard(sp)
            heapq.heappush(scores, (score, sp.id))
        top_n = heapq.nlargest(n, scores, key=lambda x: x[0])
        return [(s, self.sketchpads[i]) for s, i in top_n]

    def find_joinables_html(self, url=None, apiKey=None):
        self.upload(url=url, apiKey=apiKey)
        # now get the matching
        resp = requests.get(
            (url or "http://localhost:8000/api") + "/component/get_approx_best_joins",
            json=list(self.sketchpads.keys()),
            headers={"Authorization": f"Bearer {apiKey}"},
        )
        if resp.status_code != 200:
            raise Exception(f"Error getting joinables: {resp.text}")
        from IPython.core.display import HTML, display

        display(HTML(resp.text))

    def find_joinables(self, url=None, apiKey=None):
        self.upload(url=url, apiKey=apiKey)
        # now get the matching
        resp = requests.get(
            (url or "http://localhost:8000/api") + "/get_approx_best_joins",
            json=list(self.sketchpads.keys()),
            headers={"Authorization": f"Bearer {apiKey}"},
        )
        if resp.status_code != 200:
            raise Exception(f"Error getting joinables: {resp.text}")
        for x in resp.json():
            left_sketchpad = SketchPad.from_dict(x["left_sketchpad"])
            right_sketchpad = SketchPad.from_dict(x["right_sketchpad"])
            print(
                f"{x['score']:0.4f}  "
                + left_sketchpad.metadata["reference"]["data"]["column"]
                + " -- "
                + right_sketchpad.reference_repr()
            )

    def upload(self, url=None, apiKey=None, batch=False):
        # TODO: Try and get URL from a global state variable
        # TODO: try and get api key from global state variable
        if url is None:
            # TODO: if no url is provided, we should assume sketch.dev in future.
            url = "http://localhost:8000/api"
        if batch:
            response = requests.post(
                url + "/upload_portfolio",
                json=[x.to_dict() for x in self.sketchpads.values()],
                headers={"Authorization": f"Bearer {apiKey}"},
            )
            if response.status_code != 200:
                logging.error(f"Error uploading portfolio: {response.text}")
        else:
            for skechpad in self.sketchpads.values():
                response = requests.post(
                    url + "/upload_sketchpad",
                    json=skechpad.to_dict(),
                    headers={"Authorization": f"Bearer {apiKey}"},
                )
                if response.status_code != 200:
                    logging.error(f"Failed to upload sketchpad {skechpad.id}")
                    logging.error(response.text)
                    return False
