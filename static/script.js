document.addEventListener('DOMContentLoaded', function () {

    // ==========================================
    // SHARED TOAST HELPER FUNCTION
    // ==========================================
    function showToast(message, type = 'success') {
        const existingToast = document.getElementById('custom-toast-container');
        if (existingToast) existingToast.remove();

        const toastContainer = document.createElement('div');
        toastContainer.id = 'custom-toast-container';
        toastContainer.className = 'bottom-toast-container';

        const toastMessage = document.createElement('div');
        toastMessage.className = `toast-message ${type}`;
        toastMessage.innerText = message;

        toastContainer.appendChild(toastMessage);
        document.body.appendChild(toastContainer);

        setTimeout(() => {
            toastContainer.style.transition = 'opacity 0.5s ease';
            toastContainer.style.opacity = '0';
            setTimeout(() => toastContainer.remove(), 500);
        }, 4000);
    }

    // ==========================================
    // 1. DONOR ELIGIBILITY QUIZ LOGIC (Quiz Page)
    // ==========================================
    const nextBtn = document.querySelector('.next-button');

    if (nextBtn) {
        const quizData = [
            {
                question: "Are you in the age group of 18-60 years old?",
                options: ["Yes", "No"],
                eligibleAnswer: "yes"
            },
            {
                question: "Do you weigh at least 45 kg (99 lbs)?",
                options: ["Yes", "No"],
                eligibleAnswer: "yes"
            },
            {
                question: "Have you had any tattoos or piercings in the last 6 months?",
                options: ["Yes", "No"],
                eligibleAnswer: "no"
            },
            {
                question: "Are you currently taking any prescription medications?",
                options: ["Yes", "No"],
                eligibleAnswer: "no"
            },
            {
                question: "Have you donated blood within the past 12 weeks?",
                options: ["Yes", "No"],
                eligibleAnswer: "no"
            }
        ];

        let currentQuestionIndex = 0;
        const totalQuestions = quizData.length;
        let userAnswers = new Array(totalQuestions).fill(null);

        const questionTitle = document.getElementById('question-title');
        const questionText = document.getElementById('question-text');
        const optionsContainer = document.getElementById('options-container');
        const progressText = document.querySelector('.progress');
        const progressFill = document.querySelector('.progress-bar-fill');
        const prevBtn = document.querySelector('.previous-button');

        function loadQuestion() {
            const currentData = quizData[currentQuestionIndex];

            if (questionTitle) questionTitle.innerText = `Question ${currentQuestionIndex + 1}`;
            if (questionText) questionText.innerText = currentData.question;

            if (optionsContainer) {
                optionsContainer.innerHTML = '';
                currentData.options.forEach((opt) => {
                    const optValue = opt.toLowerCase();
                    const isChecked = userAnswers[currentQuestionIndex] === optValue ? 'checked' : '';
                    const isSelected = userAnswers[currentQuestionIndex] === optValue ? 'selected' : '';

                    optionsContainer.innerHTML += `
                        <label class="option ${isSelected}">
                            <input type="radio" name="quiz_option" value="${optValue}" ${isChecked}>
                            <span class="option-text">${opt}</span>
                            <span class="custom-radio"></span>
                        </label>
                    `;
                });
            }

            attachRadioListeners();

            const percentage = Math.round(((currentQuestionIndex + 1) / totalQuestions) * 100);
            if (progressText) progressText.innerText = percentage + '%';
            if (progressFill) progressFill.style.setProperty('--progress-width', percentage + '%');

            if (prevBtn) {
                prevBtn.disabled = currentQuestionIndex === 0;
                prevBtn.classList.toggle('disabled', currentQuestionIndex === 0);
            }

            if (currentQuestionIndex === totalQuestions - 1) {
                nextBtn.innerHTML = 'Finish <i class="fa-solid fa-check"></i>';
            } else {
                nextBtn.innerHTML = 'Next <i class="fa-solid fa-arrow-right"></i>';
            }
        }

        function attachRadioListeners() {
            const radioInputs = document.querySelectorAll('#options-container input[type="radio"]');
            radioInputs.forEach(input => {
                input.addEventListener('change', function () {
                    document.querySelectorAll('#options-container .option').forEach(option => {
                        option.classList.remove('selected');
                    });
                    if (this.checked) {
                        this.closest('.option').classList.add('selected');
                        userAnswers[currentQuestionIndex] = this.value;
                    }
                });
            });
        }

        function saveCurrentAnswer() {
            const selectedRadio = document.querySelector('#options-container input[type="radio"]:checked');
            if (selectedRadio) {
                userAnswers[currentQuestionIndex] = selectedRadio.value;
            }
        }

        nextBtn.addEventListener('click', function () {
            saveCurrentAnswer();

            if (userAnswers[currentQuestionIndex] === null) {
                showToast('Please select an answer to continue.', 'error');
                return;
            }

            if (currentQuestionIndex < totalQuestions - 1) {
                currentQuestionIndex++;
                loadQuestion();
            } else {
                const eligible = quizData.every((q, i) => userAnswers[i] === q.eligibleAnswer);

                if (eligible) {
                    showToast('Based on your answers, you appear to be eligible. Redirecting...', 'success');
                    setTimeout(() => {
                        window.location.href = "/make_appointment";
                    }, 2500);
                } else {
                    showToast('You may not be eligible right now. Redirecting to FAQ...', 'error');
                    setTimeout(() => {
                        window.location.href = "/donor_faq";
                    }, 2500);
                }
            }
        });

        if (prevBtn) {
            prevBtn.addEventListener('click', function () {
                if (currentQuestionIndex === 0) return;

                saveCurrentAnswer();
                currentQuestionIndex--;
                loadQuestion();
            });
        }

        loadQuestion();
    }


    // ==========================================
    // 2. BLOOD INVENTORY & ANNOUNCEMENT LOGIC (Staff/Admin Stock Management Page)
    // ==========================================
    const bloodTableBody = document.getElementById('bloodTableBody');

    if (bloodTableBody) {
        let globalInventoryData = [];
        let selectedBloodTypeForAnnouncement = null;

        fetchBloodInventory();

        const bloodTypeFilter = document.getElementById('bloodTypeFilter');
        const statusFilter = document.getElementById('statusFilter');
        const sortBlood = document.getElementById('sortBlood');

        if (bloodTypeFilter) bloodTypeFilter.addEventListener('change', applyFiltersAndSort);
        if (statusFilter) statusFilter.addEventListener('change', applyFiltersAndSort);
        if (sortBlood) sortBlood.addEventListener('change', applyFiltersAndSort);

        const confirmSendBtn = document.getElementById('confirmSendBtn');
        if (confirmSendBtn) {
            confirmSendBtn.addEventListener('click', function() {
                if (!selectedBloodTypeForAnnouncement) return;

                const modalEl = document.getElementById('announcementModal');
                const modalInstance = bootstrap.Modal.getInstance(modalEl);
                if (modalInstance) {
                    modalInstance.hide();
                }

                fetch('/api/send_blood_announcement', {
                    method: 'POST',
                    headers: {
                        'Content-Type': 'application/json',
                    },
                    body: JSON.stringify({ blood_type: selectedBloodTypeForAnnouncement })
                })
                .then(response => response.json())
                .then(result => {
                    if (result.success) {
                        showToast(result.message || `Announcement successfully sent for blood type ${selectedBloodTypeForAnnouncement}!`, 'success');
                    } else {
                        showToast(`Failed to send announcement: ${result.message}`, 'error');
                    }
                })
                .catch(error => {
                    console.error('Error:', error);
                    showToast('An error occurred while communicating with the server.', 'error');
                });
            });
        }

        function fetchBloodInventory() {
            fetch('/api/blood_inventory')
                .then(response => response.json())
                .then(result => {
                    if (result.success) {
                        globalInventoryData = result.data;
                        updateSummaryCards(globalInventoryData);
                        applyFiltersAndSort();
                    } else {
                        console.error("Failed to load inventory data");
                    }
                })
                .catch(error => console.error('Error fetching inventory:', error));
        }

        function updateSummaryCards(data) {
            let totalUnits = 0;
            let sufficientCount = 0;
            let lowOrCriticalCount = 0;
            let bloodTypesSet = new Set();

            data.forEach(item => {
                totalUnits += item.available_units;
                bloodTypesSet.add(item.blood_type);

                if (item.status === 'Sufficient') {
                    sufficientCount++;
                } else {
                    lowOrCriticalCount++;
                }
            });

            const totalUnitsEl = document.getElementById('totalUnits');
            const typeCountEl = document.getElementById('typeCount');
            const sufficientCountEl = document.getElementById('sufficientCount');
            const lowCountEl = document.getElementById('lowCount');

            if (totalUnitsEl) totalUnitsEl.innerText = totalUnits;
            if (typeCountEl) typeCountEl.innerText = bloodTypesSet.size;
            if (sufficientCountEl) sufficientCountEl.innerText = sufficientCount;
            if (lowCountEl) lowCountEl.innerText = lowOrCriticalCount;

            const alertBox = document.getElementById('criticalAlert');
            const alertText = document.getElementById('criticalAlertText');
            if (alertBox && alertText) {
                if (lowOrCriticalCount > 0) {
                    alertBox.style.display = 'flex';
                    alertText.innerText = `Warning: There are ${lowOrCriticalCount} blood type(s) running Low or Critical!`;
                } else {
                    alertBox.style.display = 'none';
                }
            }
        }

        function applyFiltersAndSort() {
            const selectedType = document.getElementById('bloodTypeFilter')?.value || 'All';
            const selectedStatus = document.getElementById('statusFilter')?.value || 'All';
            const sortOption = document.getElementById('sortBlood')?.value || 'desc';

            let filtered = globalInventoryData.filter(item => {
                const matchesType = (selectedType === 'All' || item.blood_type === selectedType);
                const matchesStatus = (selectedStatus === 'All' || item.status === selectedStatus);
                return matchesType && matchesStatus;
            });

            filtered.sort((a, b) => {
                if (sortOption === 'desc') {
                    return b.available_units - a.available_units;
                } else if (sortOption === 'asc') {
                    return a.available_units - b.available_units;
                } else if (sortOption === 'type') {
                    return a.blood_type.localeCompare(b.blood_type);
                }
                return 0;
            });

            renderTable(filtered);
        }

        function renderTable(data) {
            const tbody = document.getElementById('bloodTableBody');
            tbody.innerHTML = '';

            if (data.length === 0) {
                tbody.innerHTML = `<tr><td colspan="5" class="text-center py-4 text-muted">No blood inventory records found matching your filters.</td></tr>`;
                return;
            }

            data.forEach(item => {
                let badgeClass = 'bg-success bg-opacity-10 text-success';
                if (item.status === 'Low') badgeClass = 'bg-warning bg-opacity-10 text-warning text-dark';
                if (item.status === 'Critical') badgeClass = 'bg-danger bg-opacity-10 text-danger';

                let actionHtml = '<span class="text-muted small">—</span>';
                if (item.status === 'Critical') {
                    actionHtml = `
                        <button class="btn btn-sm btn-outline-danger px-3 action-view-btn" onclick="sendAnnouncement('${item.blood_type}')">
                            <i class="fa-solid fa-bullhorn me-1"></i> Send Announcement
                        </button>
                    `;
                }

                const row = `
                    <tr>
                        <td class="fw-bold px-3">${item.blood_type}</td>
                        <td>${item.available_units} Units</td>
                        <td><span class="badge ${badgeClass} px-2.5 py-1.5 badge-custom">${item.status}</span></td>
                        <td class="text-muted small">${item.last_updated}</td>
                        <td class="text-end">
                            ${actionHtml}
                        </td>
                    </tr>
                `;
                tbody.innerHTML += row;
            });
        }

        window.sendAnnouncement = function(bloodType) {
            selectedBloodTypeForAnnouncement = bloodType;
            const modalBloodTypeEl = document.getElementById('modalBloodType');
            if (modalBloodTypeEl) {
                modalBloodTypeEl.innerText = bloodType;
            }

            const modalElement = document.getElementById('announcementModal');
            if (modalElement) {
                const announcementModal = new bootstrap.Modal(modalElement);
                announcementModal.show();
            }
        };

        window.resetFilters = function() {
            if (document.getElementById('bloodTypeFilter')) document.getElementById('bloodTypeFilter').value = 'All';
            if (document.getElementById('statusFilter')) document.getElementById('statusFilter').value = 'All';
            if (document.getElementById('sortBlood')) document.getElementById('sortBlood').value = 'desc';
            applyFiltersAndSort();
        };
    }

});