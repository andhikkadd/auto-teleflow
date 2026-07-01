
    function triggerDeleteModal(id) {
        document.getElementById('deleteTargetId').innerText = id;
        document.getElementById('deleteForm').action = '/templates/' + id + '/delete';
        new bootstrap.Modal(document.getElementById('deleteModal')).show();
    }

    function toggleSelectAll(type) {
        const selectAllChk = document.getElementById(type === 'regular' ? 'selectAllRegular' : 'selectAllOverride');
        const checkboxes = document.querySelectorAll(type === 'regular' ? '.regular-checkbox' : '.override-checkbox');
        checkboxes.forEach(chk => {
            chk.checked = selectAllChk.checked;
        });
        updateSelectedCount(type);
    }

    function updateSelectedCount(type) {
        const checkboxes = document.querySelectorAll(type === 'regular' ? '.regular-checkbox' : '.override-checkbox');
        let selectedCount = 0;
        checkboxes.forEach(chk => {
            if (chk.checked) selectedCount++;
        });
        
        const countSpan = document.getElementById(type === 'regular' ? 'selectedRegularCount' : 'selectedOverrideCount');
        const deleteBtn = document.getElementById(type === 'regular' ? 'deleteSelectedRegularBtn' : 'deleteSelectedOverrideBtn');
        
        if (countSpan) countSpan.innerText = selectedCount;
        
        if (deleteBtn) {
            if (selectedCount > 0) {
                deleteBtn.classList.remove('d-none');
            } else {
                deleteBtn.classList.add('d-none');
            }
        }
        
        const selectAllChk = document.getElementById(type === 'regular' ? 'selectAllRegular' : 'selectAllOverride');
        if (selectAllChk) {
            selectAllChk.checked = (selectedCount === checkboxes.length && checkboxes.length > 0);
        }
    }

    function triggerDeleteSelectedModal(type) {
        const checkboxes = document.querySelectorAll(type === 'regular' ? '.regular-checkbox' : '.override-checkbox');
        const selectedIds = [];
        checkboxes.forEach(chk => {
            if (chk.checked) selectedIds.push(chk.value);
        });
        
        if (selectedIds.length === 0) return;
        
        document.getElementById('deleteCountText').innerText = selectedIds.length;
        document.getElementById('deleteMultipleIdsInput').value = selectedIds.join(',');
        new bootstrap.Modal(document.getElementById('deleteMultipleModal')).show();
    }

    // Persist active tab across reloads using localStorage
    document.addEventListener("DOMContentLoaded", function() {
        const activeTabId = localStorage.getItem("activeTemplateTab");
        if (activeTabId) {
            const tabEl = document.querySelector(`#${activeTabId}`);
            if (tabEl) {
                const tab = new bootstrap.Tab(tabEl);
                tab.show();
            }
        }

        const tabLinks = document.querySelectorAll('button[data-bs-toggle="tab"]');
        tabLinks.forEach(link => {
            link.addEventListener("shown.bs.tab", function(e) {
                localStorage.setItem("activeTemplateTab", e.target.id);
            });
        });

        // Timezone conversion for override until
        const overrideUntilRaw = "2026-07-01 12:00:00";
        const untilInput = document.getElementById("override_until");
        if (overrideUntilRaw && untilInput) {
            let date;
            if (overrideUntilRaw.endsWith("Z") || overrideUntilRaw.includes("+")) {
                date = new Date(overrideUntilRaw);
            } else {
                // Parse naive string (fallback)
                date = new Date(overrideUntilRaw + "Z");
            }
            if (!isNaN(date.getTime())) {
                const year = date.getFullYear();
                const month = String(date.getMonth() + 1).padStart(2, '0');
                const day = String(date.getDate()).padStart(2, '0');
                const hours = String(date.getHours()).padStart(2, '0');
                const minutes = String(date.getMinutes()).padStart(2, '0');
                untilInput.value = `${year}-${month}-${day}T${hours}:${minutes}`;
            }
        }

        // Display string timezone conversion
        const displayEl = document.getElementById("override_until_display");
        if (displayEl && displayEl.textContent.trim()) {
            const rawVal = displayEl.textContent.trim();
            let date;
            if (rawVal.endsWith("Z") || rawVal.includes("+")) {
                date = new Date(rawVal);
            } else {
                date = new Date(rawVal + "Z");
            }
            if (!isNaN(date.getTime())) {
                // Format in user's locale
                displayEl.textContent = date.toLocaleString();
            }
        }

        // On form submit, convert the local datetime to UTC ISO string
        const overrideForm = document.getElementById("overrideForm");
        if (overrideForm) {
            overrideForm.addEventListener("submit", function(e) {
                const localVal = untilInput.value;
                if (localVal) {
                    const localDate = new Date(localVal);
                    if (!isNaN(localDate.getTime())) {
                        document.getElementById("override_until_utc").value = localDate.toISOString();
                    }
                }
            });
        }
    });
