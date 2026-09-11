## 1. Web UI Layout

- [x] 1.1 Add a new HTML `<div>` container in `dashboard.h` to hold the power consumption demo (e.g. below the Ratios table).
- [x] 1.2 Add CSS styles for the comparison bars (e.g. `.power-bar`, `.bar-fill`) to allow dynamic width adjustment.

## 2. JavaScript Logic

- [x] 2.1 Update the `updateStats()` JavaScript function in `dashboard.h` to extract the energy consumption values for each protocol from the `/api/energy` JSON response.
- [x] 2.2 Implement logic to calculate the relative percentage of each algorithm compared to the highest consumer (ECC) to set the `width` style property of the bars.
- [x] 2.3 Render the calculated bars into the new HTML container upon every refresh.
