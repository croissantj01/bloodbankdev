document.addEventListener('DOMContentLoaded', function () {
    const nextBtn = document.querySelector('.next-button');

    if (!nextBtn) return;

    const quizData = [
        {
            question: "Are you in the age group of 18-60 years old?",
            options: ["Yes", "No"]
        },
        {
            question: "Do you weigh at least 50 kg (110 lbs)?",
            options: ["Yes", "No"]
        },
        {
            question: "Have you had any tattoos or piercings in the last 6 months?",
            options: ["Yes", "No"]
        },
        {
            question: "Are you currently taking any prescription medications?",
            options: ["Yes", "No"]
        },
        {
            question: "Have you donated blood within the past 12 weeks?",
            options: ["Yes", "No"]
        }
    ];

    let currentQuestionIndex = 0;
    const totalQuestions = quizData.length;

    let userAnswers = new Array(totalQuestions).fill('yes');

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
        currentData.options.forEach((opt, index) => {
            const optValue = opt.toLowerCase();
            const isChecked = userAnswers[currentQuestionIndex] === optValue ? 'checked' : '';
            const isSelected = userAnswers[currentQuestionIndex] === optValue ? 'selected' : '';

            optionsContainer.innerHTML += `
                <label class="option ${isSelected}">
                    <input type="radio" name="quiz_option" value="${opt.toLowerCase()}" ${isChecked}>
                    <span class="option-text">${opt}</span>
                    <span class="custom-radio"></span>
                </label>
            `;
        });

        attachRadioListeners();

        let percentage = Math.round(((currentQuestionIndex + 1) / totalQuestions) * 100);
        progressText.innerText = percentage + '%';
        progressFill.style.setProperty('--progress-width', percentage + '%');

        prevBtn.disabled = currentQuestionIndex === 0;
        if (currentQuestionIndex === totalQuestions - 1) {
            nextBtn.innerHTML = 'Finish <i class="fa-solid fa-check"></i>';
        } else {
            nextBtn.innerHTML = 'Next <i class="fa-solid fa-arrow-right"></i>';
        }
    }

    function attachRadioListeners() {
        const radioInputs = document.querySelectorAll('.options input[type="radio"]');
        radioInputs.forEach(input => {
            input.addEventListener('change', function() {
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

nextBtn.addEventListener('click', function() {
        saveCurrentAnswer();

        if (currentQuestionIndex < totalQuestions - 1) {
            currentQuestionIndex++;
            loadQuestion();
        } else {
            const allYes = userAnswers.every(answer => answer === 'yes');

            if (allYes) {
                alert('You are eligible for blood donation. Sign up now!');
                window.location.href = "/signup";
            } else {
                alert('Thank you for completing the quiz but you are currently not eligible for blood donation.');
                window.location.href = "/faq";
            }
        }
    });

    prevBtn.addEventListener('click', function() {
        saveCurrentAnswer();

        if (currentQuestionIndex > 0) {
            currentQuestionIndex--;
            loadQuestion();
        }
    });

    loadQuestion();
    attachRadioListeners();
});