/**
 * Simple Search Filter for Money Tracker
 * Filters table rows by location column
 */
document.addEventListener('DOMContentLoaded', function() {
    const searchInput = document.getElementById("moneySearchInput");
    const recordTable = document.getElementById("moneyRecordTable");
    const rows = document.querySelectorAll(".money-row");

    if (searchInput && recordTable) {
        searchInput.addEventListener("keyup", function() {
            const query = this.value.toLowerCase();

            rows.forEach(row => {
                // The location is in the second cell (index 1)
                const locationCell = row.cells[1];
                if (locationCell) {
                    const locationText = locationCell.textContent.toLowerCase();
                    
                    if (locationText.includes(query)) {
                        row.style.display = "";
                    } else {
                        row.style.display = "none";
                    }
                }
            });
        });
    }
});
