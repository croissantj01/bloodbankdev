document.addEventListener('DOMContentLoaded', function () {
    const nextBtn = document.querySelector('.next-button');

    if (!nextBtn) return;

    // eligibleAnswer = the answer that keeps the donor eligible for that question
    const quizData = [
        {
            // PDN: first-time donors up to 60; general range is 17-70. Change here if you want 17.
            question: "Are you in the age group of 18-60 years old?",
            options: ["Yes", "No"],
            eligibleAnswer: "yes"
        },
        {
            // PDN minimum for whole blood donation is 45 kg
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
            // Stricter than real screening: many medications are still acceptable.
            question: "Are you currently taking any prescription medications?",
            options: ["Yes", "No"],
            eligibleAnswer: "no"
        },
        {
            // Verify the interval against the PDN guideline (some sources say 56 days).
            question: "Have you donated blood within the past 12 weeks?",
            options: ["Yes", "No"],
            eligibleAnswer: "no"
        }
    ];

    let currentQuestionIndex = 0;
    const totalQuestions = quizData.length;

    // null = not answered yet (so the user has to pick an answer)
    let userAnswers = new Array(totalQuestions).fill(null);

    const questionTitle = document.getElementById('question-title');
    const questionText = document.getElementById('question-text');
    const optionsContainer = document.getElementById('options-container');
    const progressText = document.querySelector('.progress');
    const progressFill = document.querySelector('.progress-bar-fill');
    const prevBtn = document.querySelector('.previous-button');

    function loadQuestion() {
        const currentData = quizData[currentQuestionIndex];

        questionTitle.innerText = `Question ${currentQuestionIndex + 1}`;
        questionText.innerText = currentData.question;

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

        attachRadioListeners();

        // progressText must be a text-only element (not the parent of the bar)
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
        const radioInputs = document.querySelectorAll('.options input[type="radio"]');
        radioInputs.forEach(input => {
            input.addEventListener('change', function () {
                document.querySelectorAll('.options .option').forEach(option => {
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
        const selectedRadio = document.querySelector('.options input[type="radio"]:checked');
        if (selectedRadio) {
            userAnswers[currentQuestionIndex] = selectedRadio.value;
        }
    }

    nextBtn.addEventListener('click', function () {
        saveCurrentAnswer();

        if (userAnswers[currentQuestionIndex] === null) {
            alert('Please select an answer to continue.');
            return;
        }

        if (currentQuestionIndex < totalQuestions - 1) {
            currentQuestionIndex++;
            loadQuestion();
        } else {
            // eligible only if every answer matches that question's eligible answer
            const eligible = quizData.every((q, i) => userAnswers[i] === q.eligibleAnswer);

            if (eligible) {
                alert('Based on your answers, you appear to be eligible to donate blood. Sign up now!');
                window.location.href = "/signup";
            } else {
                alert('Thank you for completing the quiz. Based on your answers you may not be eligible right now. Final eligibility is decided by blood bank staff after screening.');
                window.location.href = "/faq";
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
});