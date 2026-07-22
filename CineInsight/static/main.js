/**
 * CineInsight Main JavaScript
 * Handles header transitions, interactive elements, and micro-interactions
 */

document.addEventListener('DOMContentLoaded', () => {
    // 1. Header scroll effect
    const header = document.querySelector('.main-header');
    
    const handleScroll = () => {
        if (window.scrollY > 20) {
            header.classList.add('scrolled');
        } else {
            header.classList.remove('scrolled');
        }
    };

    window.addEventListener('scroll', handleScroll);
    // Trigger once on load in case page is loaded scrolled
    handleScroll();

    // 2. Micro-interactions for primary buttons (ripple-like active state scale)
    const primaryBtns = document.querySelectorAll('.btn-primary');
    
    primaryBtns.forEach(btn => {
        btn.addEventListener('click', (e) => {
            // Log interaction or handle action
            console.log(`Action triggered: ${btn.textContent.trim()}`);
            
            // Simple bounce effect on click
            btn.style.transform = 'scale(0.96)';
            setTimeout(() => {
                btn.style.transform = '';
            }, 100);
        });
    });

    // 3. Smooth scroll for feature anchor links
    const navLinks = document.querySelectorAll('.nav-link');
    
    navLinks.forEach(link => {
        link.addEventListener('click', (e) => {
            const href = link.getAttribute('href');
            if (href.startsWith('#') && href.length > 1) {
                e.preventDefault();
                const targetElement = document.querySelector(href);
                if (targetElement) {
                    targetElement.scrollIntoView({
                        behavior: 'smooth',
                        block: 'start'
                    });
                }
            }
        });
    });

    // 4. Feature Card Active States (adds interactive class when scrolled into view on mobile)
    const featureCards = document.querySelectorAll('.feature-card');
    
    if ('IntersectionObserver' in window) {
        const cardObserver = new IntersectionObserver((entries) => {
            entries.forEach(entry => {
                if (entry.isIntersecting) {
                    entry.target.style.opacity = '1';
                    entry.target.style.transform = 'translateY(0)';
                }
            });
        }, {
            threshold: 0.1,
            rootMargin: '0px 0px -50px 0px'
        });
        
        featureCards.forEach(card => {
            cardObserver.observe(card);
        });
    }

    // 5. Password visibility toggler
    const passwordInput = document.getElementById('password');
    const passwordToggle = document.getElementById('password-toggle');
    
    if (passwordInput && passwordToggle) {
        passwordToggle.addEventListener('click', () => {
            const isPassword = passwordInput.getAttribute('type') === 'password';
            passwordInput.setAttribute('type', isPassword ? 'text' : 'password');
            
            if (isPassword) {
                // Show password: change to eye-off (slashed) icon with active primary color
                passwordToggle.innerHTML = `
                    <svg class="eye-icon" width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="var(--color-primary, #E35614)" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" xmlns="http://www.w3.org/2000/svg">
                        <path d="M17.94 17.94A10.07 10.07 0 0 1 12 20c-7 0-11-8-11-8a18.45 18.45 0 0 1 5.06-5.94M9.9 4.24A9.12 9.12 0 0 1 12 4c7 0 11 8 11 8a18.5 18.5 0 0 1-2.16 3.19m-6.72-1.07a3 3 0 1 1-4.24-4.24"></path>
                        <line x1="1" y1="1" x2="23" y2="23"></line>
                    </svg>
                `;
                passwordToggle.setAttribute('aria-label', 'Hide password');
            } else {
                // Hide password: change to normal eye icon with neutral gray color
                passwordToggle.innerHTML = `
                    <svg class="eye-icon" width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="#94A3B8" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" xmlns="http://www.w3.org/2000/svg">
                        <path d="M1 12C1 12 5 4 12 4C19 4 23 12 23 12C23 12 19 20 12 20C5 20 1 12 1 12Z" />
                        <circle cx="12" cy="12" r="3" />
                    </svg>
                `;
                passwordToggle.setAttribute('aria-label', 'Show password');
            }
        });
    }

    // 6. Sign In Form Redirect to Dashboard with credentials check
    const signinForm = document.getElementById('signin-form');
    if (signinForm) {
        signinForm.addEventListener('submit', (e) => {
            e.preventDefault();
            
            const emailInput = document.getElementById('email');
            const passwordInput = document.getElementById('password');
            if (!emailInput || !passwordInput) return;

            const email = emailInput.value.trim();
            const password = passwordInput.value;

            // Load registered users from "database" (localStorage)
            const users = JSON.parse(localStorage.getItem('users')) || [];
            
            // Check credentials
            const user = users.find(u => u.email.toLowerCase() === email.toLowerCase() && u.password === password);

            if (user) {
                // Save current session
                localStorage.setItem('currentUser', JSON.stringify({ name: user.name, email: user.email }));
                window.location.href = 'dashboard.html';
            } else {
                alert("Email or password incorrect.");
            }
        });
    }

    // Google SSO Button click redirect
    const googleSsoBtn = document.querySelector('.google-sso-btn');
    if (googleSsoBtn) {
        googleSsoBtn.addEventListener('click', () => {
            window.location.href = 'google-login.html';
        });
    }

    // 7a. Dynamic Welcome Greeting & Sign Out Flow
    const welcomeText = document.querySelector('.welcome-text');
    if (welcomeText) {
        const currentUser = JSON.parse(localStorage.getItem('currentUser'));
        if (currentUser && currentUser.name) {
            welcomeText.textContent = `Welcome, ${currentUser.name}`;
        } else {
            welcomeText.textContent = 'Welcome, Guest';
        }

        // Click user profile panel to trigger Sign Out
        const userPanel = document.querySelector('.user-panel');
        if (userPanel) {
            userPanel.style.cursor = 'pointer';
            userPanel.setAttribute('title', 'Click to Sign Out');
            userPanel.addEventListener('click', () => {
                if (confirm("Are you sure you want to sign out?")) {
                    localStorage.removeItem('currentUser');
                    window.location.href = 'signin.html';
                }
            });
        }
    }

    // 8. Dashboard Simulation Interactions
    const btnAnalyze = document.getElementById('btn-analyze');
    const btnSearch = document.getElementById('btn-search');
    const reviewInput = document.getElementById('review-link-input');

    const triggerAnalysis = (query) => {
        if (!query || query.trim() === "") {
            alert("Please enter a valid review link or keyword.");
            return;
        }
        alert(`Initializing CineInsight multimodal analysis for: "${query}"\n\n- Extracting audio prosody...\n- Scanning micro-expressions...\n- Processing linguistic irony...\n\nOpening analysis report...`);
        window.location.href = 'analysis.html';
    };

    if (btnAnalyze && reviewInput) {
        btnAnalyze.addEventListener('click', () => triggerAnalysis(reviewInput.value));
    }
    if (btnSearch && reviewInput) {
        btnSearch.addEventListener('click', () => triggerAnalysis(reviewInput.value));
    }

    // Card click triggers
    const cardAnalyzeBtns = document.querySelectorAll('.btn-analyze-card');
    cardAnalyzeBtns.forEach(btn => {
        btn.addEventListener('click', (e) => {
            const card = btn.closest('.review-card');
            const title = card ? card.querySelector('.card-title').textContent.trim() : "this review";
            triggerAnalysis(title);
        });
    });

    // 9. Reasoning Report Trigger
    const btnReport = document.getElementById('btn-reasoning-report');
    if (btnReport) {
        btnReport.addEventListener('click', () => {
            const btnText = btnReport.querySelector('.btn-text');
            const originalText = btnText.textContent;
            btnText.textContent = "Generating Report...";
            btnReport.style.opacity = '0.7';
            btnReport.disabled = true;

            setTimeout(() => {
                btnText.textContent = originalText;
                btnReport.style.opacity = '';
                btnReport.disabled = false;
                alert("Reasoning Report successfully created!\n\n- Download ready: cineinsight_matrix_resurrections_sarcasm_report.pdf\n- Deep semantic pathways loaded.");
            }, 1500);
        });
    }
});
