"""Compare three portfolios using annual return and volatility assumptions.

Run: python portfolio.py
All rates below are decimals: 0.035 means 3.5%.
"""

# EDITABLE INPUTS: correlation rows and columns follow this sleeve order.
SLEEVES = [
    {"name": "Treasury bills", "expected_return": 0.035, "volatility": 0.005,
     "reserve_eligible": True},
    {"name": "Treasury 10-year note", "expected_return": 0.043, "volatility": 0.070,
     "reserve_eligible": True},
    {"name": "Investment-grade bond fund", "expected_return": 0.050, "volatility": 0.060,
     "reserve_eligible": False},
    {"name": "Global equity index fund", "expected_return": 0.080, "volatility": 0.160,
     "reserve_eligible": False},
]

CORRELATIONS = [
    [1.00, 0.10, 0.05, 0.00],
    [0.10, 1.00, 0.80, -0.10],
    [0.05, 0.80, 1.00, 0.25],
    [0.00, -0.10, 0.25, 1.00],
]

# CPI estimate of 2.5% plus 4 percentage points.
OBJECTIVE_RETURN = 0.065


import math
import sys
import csv
from datetime import date
import io
from pathlib import Path
import statistics


def validate_correlations(correlations, size):
    """Reject malformed, out-of-range, or asymmetric correlation tables."""
    if len(correlations) != size or any(len(row) != size for row in correlations):
        raise ValueError(f"Correlation table must have {size} rows and {size} columns.")
    for i, row in enumerate(correlations):
        for j, value in enumerate(row):
            if not math.isfinite(value) or not -1.0 <= value <= 1.0:
                raise ValueError(
                    f"Correlation at row {i + 1}, column {j + 1} must be between -1 and 1."
                )
            if value != correlations[j][i]:
                raise ValueError(
                    f"Correlation table is not symmetric: row {i + 1}, column {j + 1} "
                    f"differs from row {j + 1}, column {i + 1}."
                )
        if row[i] != 1.0:
            raise ValueError(f"Correlation diagonal at row {i + 1} must equal 1.")


def validate_inputs(sleeves, correlations, objective_return):
    """Validate assumptions before calculating or printing results."""
    if not sleeves:
        raise ValueError("At least one sleeve is required.")
    if len({sleeve["name"] for sleeve in sleeves}) != len(sleeves):
        raise ValueError("Sleeve names must be unique.")
    for sleeve in sleeves:
        if not math.isfinite(sleeve["expected_return"]):
            raise ValueError(f"Expected return for {sleeve['name']} must be finite.")
        if not math.isfinite(sleeve["volatility"]) or sleeve["volatility"] <= 0:
            raise ValueError(f"Volatility for {sleeve['name']} must be positive and finite.")
    if not math.isfinite(objective_return):
        raise ValueError("Objective return must be finite.")
    validate_correlations(correlations, len(sleeves))


def build_covariance_matrix(volatilities, correlations):
    """Return covariance[i][j] = correlation[i][j] * volatility[i] * volatility[j]."""
    validate_correlations(correlations, len(volatilities))
    return [
        [correlations[i][j] * vol_i * vol_j
         for j, vol_j in enumerate(volatilities)]
        for i, vol_i in enumerate(volatilities)
    ]


def benchmark_weights(sleeves):
    """Allocate 40% to IG bonds and 60% to global equity by sleeve name."""
    allocation = {
        "Investment-grade bond fund": 0.40,
        "Global equity index fund": 0.60,
    }
    missing = set(allocation) - {sleeve["name"] for sleeve in sleeves}
    if missing:
        raise ValueError("Benchmark sleeve missing: " + ", ".join(sorted(missing)))
    return [allocation.get(sleeve["name"], 0.0) for sleeve in sleeves]


def equal_weights(number_of_sleeves):
    """Allocate the same weight to each sleeve."""
    if number_of_sleeves <= 0:
        raise ValueError("Equal weighting requires at least one sleeve.")
    return [1.0 / number_of_sleeves] * number_of_sleeves


def normalize_weights(raw_weights):
    """Scale nonnegative weights to sum to one."""
    if any(not math.isfinite(weight) or weight < 0 for weight in raw_weights):
        raise ValueError("Weights must be nonnegative and finite.")
    total = sum(raw_weights)
    if total <= 0:
        raise ValueError("Weights must have a positive total.")
    return [weight / total for weight in raw_weights]


def inverse_volatility_weights(volatilities):
    """Normalize the reciprocal of each sleeve's volatility."""
    if any(not math.isfinite(vol) or vol <= 0 for vol in volatilities):
        raise ValueError("Inverse volatility weighting requires positive, finite volatilities.")
    return normalize_weights([1.0 / vol for vol in volatilities])


def portfolio_expected_return(weights, expected_returns):
    """Calculate the weighted mean expected return."""
    if len(weights) != len(expected_returns):
        raise ValueError("Weights and expected returns must have the same length.")
    return sum(weight * rate for weight, rate in zip(weights, expected_returns))


def portfolio_volatility(weights, covariance_matrix):
    """Calculate sqrt(w' * covariance * w)."""
    size = len(weights)
    if len(covariance_matrix) != size or any(len(row) != size for row in covariance_matrix):
        raise ValueError("Covariance dimensions must match the weights.")
    variance = sum(
        weights[i] * weights[j] * covariance_matrix[i][j]
        for i in range(size) for j in range(size)
    )
    if variance < 0:
        raise ValueError("Portfolio variance is negative; check the correlation assumptions.")
    return math.sqrt(variance)


def reserve_eligible_weight(weights, sleeves):
    """Sum the weights of reserve-eligible sleeves (bills and the 10-year note)."""
    if len(weights) != len(sleeves):
        raise ValueError("Weights and sleeves must have the same length.")
    return sum(weight for weight, sleeve in zip(weights, sleeves)
               if sleeve["reserve_eligible"])


def meets_objective(expected_return, objective_return):
    """Return whether expected return meets or exceeds the objective."""
    return expected_return >= objective_return


def search_lowest_risk(sleeves, correlations, objective_return=OBJECTIVE_RETURN,
                       reserve_minimum=0.03):
    """Return the least-volatile feasible 5-percentage-point mix, or None.

    Weights are nonnegative and sum to 100%. Rates and limits are decimals.
    Exhaustively enumerates integer allocations of twenty 5-point units.
    Ties keep the first mix encountered; feasibility allows 1e-12 roundoff.
    This is a grid optimum, not a continuous-allocation optimum.
    """
    validate_inputs(sleeves, correlations, objective_return)
    if not 1 <= len(sleeves) <= 6:
        raise ValueError("The grid search supports one to six assets.")
    if not math.isfinite(reserve_minimum) or not 0 <= reserve_minimum <= 1:
        raise ValueError("Reserve minimum must be between 0 and 1.")
    expected_returns = [sleeve["expected_return"] for sleeve in sleeves]
    covariance = build_covariance_matrix(
        [sleeve["volatility"] for sleeve in sleeves], correlations)

    def allocations(remaining, count):
        if count == 1:
            yield [remaining]
        else:
            for units in range(remaining + 1):
                for rest in allocations(remaining - units, count - 1):
                    yield [units, *rest]

    best = None
    for units in allocations(20, len(sleeves)):
        weights = [unit / 20 for unit in units]
        expected_return = portfolio_expected_return(weights, expected_returns)
        if not meets_objective(expected_return + 1e-12, objective_return):
            continue
        reserve_weight = reserve_eligible_weight(weights, sleeves)
        if reserve_weight + 1e-12 < reserve_minimum:
            continue
        volatility = portfolio_volatility(weights, covariance)
        if best is None or volatility < best["volatility"] - 1e-12:
            best = {"weights": weights, "expected_return": expected_return,
                    "volatility": volatility, "reserve_eligible_weight": reserve_weight}
    return best


def estimate_from_csv(source, last_36_months=False):
    """Estimate annual inputs from monthly Adj Close prices, not forecasts.

    Accepts a path, CSV bytes, or a file-like object. The first column contains
    ISO dates, oldest first; each remaining column is one unique ticker.
    Uses simple monthly returns, mean * 12, sample stdev * sqrt(12), and
    Pearson correlations. Last-36 mode selects 36 returns from 37 prices.
    Reserve eligibility defaults to False because prices do not establish it.
    """
    if isinstance(source, (str, Path)):
        text = Path(source).read_text(encoding="utf-8-sig")
    elif isinstance(source, bytes):
        text = source.decode("utf-8-sig")
    else:
        text = source.read()
        if isinstance(text, bytes):
            text = text.decode("utf-8-sig")
    if not isinstance(text, str):
        raise ValueError("Supply a CSV path, bytes, or a readable file.")
    rows = list(csv.reader(io.StringIO(text.lstrip("\ufeff"))))
    if not rows or len(rows[0]) < 2:
        raise ValueError("CSV needs a date column first and one column per ticker.")
    headers = [header.strip() for header in rows[0]]
    if any(not header for header in headers) or len(set(headers)) != len(headers):
        raise ValueError("CSV column names must be nonempty and unique.")
    tickers = headers[1:]
    if not 1 <= len(tickers) <= 6:
        raise ValueError("CSV must contain one to six ticker columns.")
    rows = [row for row in rows[1:] if any(cell.strip() for cell in row)]
    dates, prices = [], []
    for line, row in enumerate(rows, start=2):
        if len(row) != len(headers):
            raise ValueError(f"CSV row {line} has the wrong number of columns.")
        try:
            day = date.fromisoformat(row[0].strip())
            values = [float(cell) for cell in row[1:]]
        except ValueError as error:
            raise ValueError(f"CSV row {line} needs an ISO date and numeric prices.") from error
        if any(not math.isfinite(value) or value <= 0 for value in values):
            raise ValueError(f"CSV row {line} contains a missing, nonfinite, or nonpositive price.")
        if dates:
            month_gap = (day.year - dates[-1].year) * 12 + day.month - dates[-1].month
            if day <= dates[-1] or month_gap != 1:
                raise ValueError("CSV dates must be oldest first, with exactly one row per consecutive month.")
        dates.append(day)
        prices.append(values)
    if len(prices) < 3:
        raise ValueError("At least three monthly price rows are needed for sample statistics.")
    returns = [[current[i] / previous[i] - 1 for i in range(len(tickers))]
               for previous, current in zip(prices, prices[1:])]
    if last_36_months:
        if len(returns) < 36:
            raise ValueError("Last 36 months requires at least 37 monthly price rows.")
        returns = returns[-36:]
    series = [list(values) for values in zip(*returns)]
    volatilities = [statistics.stdev(values) * math.sqrt(12) for values in series]
    for ticker, volatility in zip(tickers, volatilities):
        if volatility <= 1e-12:
            raise ValueError(f"{ticker} has constant monthly returns; its correlation is undefined.")
    sleeves = [{"name": ticker, "expected_return": statistics.mean(values) * 12,
                "volatility": volatility, "reserve_eligible": False}
               for ticker, values, volatility in zip(tickers, series, volatilities)]
    correlations = [[1.0 if i == j else 0.0 for j in range(len(tickers))]
                    for i in range(len(tickers))]
    for i in range(len(tickers)):
        for j in range(i + 1, len(tickers)):
            correlation = max(-1.0, min(1.0, statistics.correlation(series[i], series[j])))
            correlations[i][j] = correlations[j][i] = correlation
    validate_inputs(sleeves, correlations, OBJECTIVE_RETURN)
    return {"sleeves": sleeves, "correlations": correlations,
            "months": len(returns), "price_start": str(dates[-len(returns) - 1]),
            "price_end": str(dates[-1]), "return_start": str(dates[-len(returns)]),
            "label": "Historical annualized mean returns, not forecasts"}


def main():
    """Calculate all results before printing, so invalid inputs produce no report."""
    try:
        validate_inputs(SLEEVES, CORRELATIONS, OBJECTIVE_RETURN)
        returns = [sleeve["expected_return"] for sleeve in SLEEVES]
        volatilities = [sleeve["volatility"] for sleeve in SLEEVES]
        covariance = build_covariance_matrix(volatilities, CORRELATIONS)
        portfolios = [
            ("Benchmark", benchmark_weights(SLEEVES)),
            ("Equal weight", equal_weights(len(SLEEVES))),
            ("Inverse volatility", inverse_volatility_weights(volatilities)),
        ]
        results = []
        for name, weights in portfolios:
            expected_return = portfolio_expected_return(weights, returns)
            results.append((
                name, weights, expected_return,
                portfolio_volatility(weights, covariance),
                reserve_eligible_weight(weights, SLEEVES),
                meets_objective(expected_return, OBJECTIVE_RETURN),
            ))
    except (ValueError, TypeError, KeyError, OverflowError) as error:
        print(f"Cannot run portfolio analysis: {error}", file=sys.stderr)
        return 1

    print(f"Annual objective return: {OBJECTIVE_RETURN:.2%}")
    print("All results use annual assumptions. Displayed weights are rounded.")
    for name, weights, expected_return, volatility, reserve_weight, passes in results:
        print(f"\n{name}")
        for sleeve, weight in zip(SLEEVES, weights):
            print(f"  {sleeve['name']}: {weight:.1%}")
        print(f"  Expected return: {expected_return:.2%}")
        print(f"  Volatility: {volatility:.2%}")
        print(f"  Reserve-eligible weight: {reserve_weight:.1%}")
        print(f"  Meets expected-return objective: {'Yes' if passes else 'No'}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
