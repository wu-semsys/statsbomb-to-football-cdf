# Statsbomb to Football CDF

A Python script for converting football/soccer data from [StatsBomb open-data](https://github.com/statsbomb/open-data) format to [Football Common Data Format (CDF)](https://doi.org/10.48550/arXiv.2505.15820) to semantic web-ready JSON-LD format.

## Overview

This repository provides a complete data transformation pipeline:

**StatsBomb JSON** → **Football-CDF JSON** → **Football-CDF JSON-LD**

The conversion process involves two main steps:
1. **StatsBomb to CDF**: Convert [StatsBomb open-data](https://github.com/statsbomb/open-data) JSON files to [Football Common Data Format (CDF)](https://doi.org/10.48550/arXiv.2505.15820)
2. **CDF to JSON-LD**: Transform CDF data into semantic web format using the Football-CDF ontology

## Installation

### Requirements

- Python 3.7+

### Setup

```bash
git clone https://github.com/wu-semsys/statsbomb-to-football-cdf.git
cd statsbomb-to-football-cdf
pip install -r requirements.txt
```

## Usage

### Step 1: StatsBomb to CDF Conversion

#### Single Match
```bash
python transform_to_football_cdf.py \
    --events data/events/3943043.json \
    --lineup data/lineups/3943043.json \
    --matches data/matches/43/51.json \
    --out-dir cdf_output
```

#### Batch Processing
```bash
python transform_to_football_cdf.py \
    --root /path/to/statsbomb-open-data \
    --competitions 43 49 \
    --seasons 51 4 \
    --out-dir cdf_batch_output
```

### Step 2: CDF to JSON-LD Conversion

#### Single Match
```bash
python football_cdf_to_jsonld.py \
    --sheet cdf_output/3943043/match_sheet_cdf.json \
    --events cdf_output/3943043/event_cdf.json \
    --meta cdf_output/3943043/match_meta_cdf.json \
    --out jsonld_output/3943043.jsonld
```

#### Batch Processing
```bash
python football_cdf_to_jsonld.py \
    --root cdf_batch_output \
    --out-dir jsonld_batch_output
```

## Data Formats

### Input: StatsBomb Open Data
The scripts expect StatsBomb's open-data format with the following structure:
```
data/
├── events/
│   └── {match_id}.json
├── lineups/
│   └── {match_id}.json
└── matches/
    └── {competition_id}/
        └── {season_id}.json
```

### Intermediate: Football CDF
Each match produces three CDF tables:
- `match_sheet_cdf.json` - Match overview, teams, players, results
- `event_cdf.json` - All match events with timestamps and coordinates
- `match_meta_cdf.json` - Competition, season, stadium, referee metadata

### Output: Football-CDF JSON-LD
Semantic web format following the Football-CDF ontology:
```json
{
  "@context": {
    "@vocab": "https://w3id.org/football-cdf/core#",
    "xsd": "http://www.w3.org/2001/XMLSchema#"
  },
  "@graph": [
    {
      "@id": "match_result/3943043",
      "@type": "Match_Result",
      ...
    }
  ]
}
```

## Command Line Options

### transform_to_football_cdf.py

**Single Match Mode:**
- `--events` - Path to StatsBomb events JSON file
- `--lineup` - Path to StatsBomb lineup JSON file  
- `--matches` - Path to StatsBomb matches JSON file (optional)
- `--out-dir` - Output directory (default: `cdf_out`)

**Batch Mode:**
- `--root` - Root directory of StatsBomb open-data
- `--competitions` - Space-separated competition IDs
- `--seasons` - Space-separated season IDs  
- `--out-dir` - Output directory

### football_cdf_to_jsonld.py

**Single Match Mode:**
- `--sheet` - Path to match_sheet_cdf.json
- `--events` - Path to event_cdf.json
- `--meta` - Path to match_meta_cdf.json
- `--out` - Output JSON-LD file path

**Batch Mode:**
- `--root` - Directory containing per-match CDF folders
- `--out-dir` - Output directory for JSON-LD files

## License

This project is licensed under the MIT License.

## Acknowledgments

- ![StatsBomb Icon](images/statsbomb_icon.svg)[StatsBomb](https://statsbomb.com/) for providing open football data
- [Football Common Data Format](https://doi.org/10.48550/arXiv.2505.15820)


---

**Note**: This tool is designed for research and educational purposes. Please respect StatsBomb's data usage terms and conditions.
