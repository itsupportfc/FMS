document.addEventListener("click", function (e) {
    const brokerOption = e.target.closest(".broker-option");
    if (brokerOption) {
        const brokerId = brokerOption.dataset.id;
        const brokerName = brokerOption.dataset.name;

        // update hidden select
        document.getElementById("broker_hidden").value = brokerId;
        // update visible input
        document.getElementById("broker_search").value = brokerName;

        // hide dropdown
        document.getElementById("broker_results").innerHTML = "";
        document.getElementById("broker_results").classList.add("hidden");
    }
});

// handle facility search result selection
document.addEventListener("click", function (e) {
    const facilityOption = e.target.closest(".facility-option");
    if (facilityOption) {
        const facilityId = facilityOption.dataset.id;
        const facilityName = facilityOption.dataset.name;

        const stopRow = facilityOption.closest("[data-stop-row]");
        if (!stopRow) return;

        const hiddenInput = stopRow.querySelector(
            "input[id^='facility_hidden_']",
        );
        const searchInput = stopRow.querySelector(
            "input[id^='facility_search_']",
        );
        const resultsDiv = stopRow.querySelector(
            "div[id^='facility_results_']",
        );

        if (hiddenInput) hiddenInput.value = facilityId;
        if (searchInput) searchInput.value = facilityName;
        if (resultsDiv) {
            resultsDiv.innerHTML = "";
            resultsDiv.classList.add("hidden");
        }
    }
});

// hide dropdown when clicking outside
document.addEventListener("click", function (e) {
    if (
        !e.target.matches("#broker_search") &&
        !e.target.matches("#broker_results")
    ) {
        const resultsDiv = document.getElementById("broker_results");
        if (resultsDiv) resultsDiv.classList.add("hidden");
    }

    const facilitySearch = e.target.closest(".facility-search");
    if (!facilitySearch && !e.target.closest("[id^='facility_results_']")) {
        document
            .querySelectorAll("[id^='facility_results_']")
            .forEach((resultsDiv) => resultsDiv.classList.add("hidden"));
    }
});

// show dropdown on focus
document.getElementById("broker_search").addEventListener("focus", function () {
    document.getElementById("broker_results").classList.remove("hidden");
});

document.addEventListener("focusin", function (e) {
    if (e.target.classList.contains("facility-search")) {
        const stopRow = e.target.closest("[data-stop-row]");
        if (!stopRow) return;
        const resultsDiv = stopRow.querySelector(
            "div[id^='facility_results_']",
        );
        if (resultsDiv) resultsDiv.classList.remove("hidden");
    }
});
