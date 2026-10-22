"""Run with: .venv/Scripts/python.exe -m streamlit run app.py"""

from copy import deepcopy
import hashlib
import io

import streamlit as st

from portfolio import (
    CORRELATIONS,
    OBJECTIVE_RETURN,
    SLEEVES,
    estimate_from_csv,
    search_lowest_risk,
)

DEFAULT_RESERVE_MINIMUM = 0.03
# Known Treasury-bill proxies from the Project 2 preparation; review in the UI.
CSV_RESERVE_DEFAULTS = {"SGOV", "BIL"}


@st.cache_data(show_spinner=False)
def load_prices(contents, last_36_months):
    return estimate_from_csv(io.BytesIO(contents), last_36_months)


@st.cache_data(show_spinner=False)
def find_mix(sleeves, correlations, objective, reserve_minimum):
    return search_lowest_risk(sleeves, correlations, objective, reserve_minimum)


def show_mix(result, sleeves, heading):
    st.subheader(heading)
    if result is None:
        st.warning("no mix meets the objective")
        return
    st.table([{"Asset": sleeve["name"], "Weight": f"{weight:.2%}"}
              for sleeve, weight in zip(sleeves, result["weights"])])
    st.metric("Expected annual return", f"{result['expected_return']:.2%}")
    st.metric("Annual volatility", f"{result['volatility']:.2%}")
    st.metric("Reserve-eligible weight", f"{result['reserve_eligible_weight']:.2%}")


def main():
    st.set_page_config(page_title="Portfolio mix lab", layout="wide")
    st.title("Portfolio mix lab")
    st.caption("Built with AI help, a learning demonstration, not investment advice.")

    with st.sidebar:
        st.header("Mandate")
        objective = st.number_input("Annual return objective (%)", value=OBJECTIVE_RETURN * 100,
                                    step=1.0, format="%.2f", key="objective") / 100
        reserve_minimum = st.number_input("Reserve minimum (%)", min_value=0.0, max_value=100.0,
                                          value=DEFAULT_RESERVE_MINIMUM * 100,
                                          step=1.0, format="%.2f", key="reserve_minimum") / 100
        upload = st.file_uploader("Upload prices.csv", type=["csv"], key="prices_upload")
        last_36 = st.toggle("Last 36 months only", value=False, disabled=upload is None,
                            key="last_36", help="Uses 36 monthly returns, requiring 37 prices.")

    if upload is None:
        source_key = "meridian"
        loaded_sleeves = deepcopy(SLEEVES)
        loaded_correlations = deepcopy(CORRELATIONS)
        current_inputs = {"sleeves": deepcopy(SLEEVES), "correlations": deepcopy(CORRELATIONS)}
        st.write("Meridian training inputs")
        st.caption("Annual assumptions from portfolio.py. Upload prices.csv to use your Project 2 funds.")
    else:
        contents = upload.getvalue()
        source_key = hashlib.sha256(contents).hexdigest()
        try:
            loaded_inputs = load_prices(contents, False)
            current_inputs = load_prices(contents, last_36)
        except (ValueError, UnicodeError, TypeError, OverflowError) as error:
            st.error(f"Cannot estimate inputs: {error}")
            st.stop()
        loaded_sleeves = deepcopy(loaded_inputs["sleeves"])
        loaded_correlations = loaded_inputs["correlations"]
        for sleeve in loaded_sleeves:
            sleeve["reserve_eligible"] = sleeve["name"].upper() in CSV_RESERVE_DEFAULTS
        for sleeve in current_inputs["sleeves"]:
            sleeve["reserve_eligible"] = sleeve["name"].upper() in CSV_RESERVE_DEFAULTS
        st.write("Project 2 fund inputs")
        st.caption(f"Historical annualized mean returns, not forecasts. "
                   f"{current_inputs['months']} monthly returns from "
                   f"{current_inputs['price_start']} through {current_inputs['price_end']}. "
                   "Fund expenses are embedded; additional costs are excluded.")
        st.caption("SGOV and BIL default to reserve-eligible as Treasury-bill proxies. "
                   "Review the boxes for your mandate; other uploaded tickers start unticked.")

    st.subheader("Edit the inputs")
    st.caption("Return boxes use annual percentages. Volatility and correlation stay at the loaded "
               "values, or are re-estimated from the selected CSV window.")
    edited_sleeves = deepcopy(current_inputs["sleeves"])
    window_key = "36" if upload is not None and last_36 else "all"
    for index, sleeve in enumerate(edited_sleeves):
        name_column, return_column, reserve_column = st.columns([2, 2, 2])
        name_column.write(sleeve["name"])
        sleeve["expected_return"] = return_column.number_input(
            f"Expected annual return (%) — {sleeve['name']}",
            value=float(sleeve["expected_return"] * 100), step=1.0, format="%.2f",
            key=f"return_{source_key}_{window_key}_{index}") / 100
        sleeve["reserve_eligible"] = reserve_column.checkbox(
            f"Reserve-eligible — {sleeve['name']}", value=sleeve["reserve_eligible"],
            key=f"eligible_{source_key}_{index}")

    try:
        loaded_result = find_mix(loaded_sleeves, loaded_correlations,
                                 OBJECTIVE_RETURN, DEFAULT_RESERVE_MINIMUM)
        edited_result = find_mix(edited_sleeves, current_inputs["correlations"],
                                 objective, reserve_minimum)
    except ValueError as error:
        st.error(f"Cannot search these inputs: {error}")
        st.stop()

    st.caption("Lowest risk among fully invested, long-only mixes in 5-percentage-point steps. "
               "A 3% reserve minimum therefore requires at least 5% on this grid.")
    current_column, loaded_column = st.columns(2)
    with current_column:
        show_mix(edited_result, edited_sleeves, "Lowest-risk mix with your edits")
        st.caption(f"Objective {objective:.2%}; reserve minimum {reserve_minimum:.2%}.")
    with loaded_column:
        show_mix(loaded_result, loaded_sleeves, "Lowest-risk mix as loaded")
        st.caption("Original returns and reserve flags; objective 6.50%; reserve minimum 3.00%. "
                   + ("CSV uses all months." if upload is not None else "Meridian assumptions."))

    if loaded_result is None or edited_result is None:
        st.info("Largest weight change: unavailable because one or both mixes are infeasible.")
    else:
        changes = [abs(current - loaded) * 100
                   for current, loaded in zip(edited_result["weights"], loaded_result["weights"])]
        largest = max(changes)
        names = ", ".join(sleeve["name"] for sleeve, change in zip(edited_sleeves, changes)
                          if abs(change - largest) < 1e-9)
        st.metric("Largest weight change", f"{largest:.2f} percentage points")
        if largest > 0:
            st.caption(names)


if __name__ == "__main__":
    main()
