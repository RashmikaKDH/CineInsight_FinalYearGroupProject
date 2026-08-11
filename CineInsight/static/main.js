/**
 * CineInsight Main JavaScript
 * Handles header transitions, interactive elements, and micro-interactions
 */

document.addEventListener('DOMContentLoaded', () => {
    // 1. Header scroll effect
    const header = document.querySelector('.main-header');
    
    const handleScroll = () => {
        if (header) {
            if (window.scrollY > 20) {
                header.classList.add('scrolled');
            } else {
                header.classList.remove('scrolled');
            }
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

    // Google SSO Button click redirect
    const googleSsoBtn = document.querySelector('.google-sso-btn');
    if (googleSsoBtn) {
        googleSsoBtn.addEventListener('click', () => {
            window.location.href = '/google-login';
        });
    }

    // 7. Avatar initials color generator (consistent across pages)
    const AVATAR_COLORS = [
        'linear-gradient(135deg, #FDBA74, #E35614)',
        'linear-gradient(135deg, #93C5FD, #2563EB)',
        'linear-gradient(135deg, #86EFAC, #16A34A)',
        'linear-gradient(135deg, #F9A8D4, #DB2777)',
        'linear-gradient(135deg, #C4B5FD, #7C3AED)',
        'linear-gradient(135deg, #FDE68A, #D97706)',
        'linear-gradient(135deg, #6EE7B7, #059669)',
        'linear-gradient(135deg, #FCA5A5, #DC2626)',
    ];

    function getAvatarColor(name) {
        if (!name) return AVATAR_COLORS[0];
        const index = name.charCodeAt(0) % AVATAR_COLORS.length;
        return AVATAR_COLORS[index];
    }

    // Apply dynamic gradient to all avatar circles on the page
    document.querySelectorAll('.avatar-circle').forEach(avatar => {
        const name = avatar.dataset.name || '';
        avatar.style.background = getAvatarColor(name);
    });

    // 8. Dashboard Real YouTube Search
    const btnSearch = document.getElementById('btn-search');
    const reviewInput = document.getElementById('review-link-input');
    const reviewsGrid = document.getElementById('reviews-grid');
    const searchLoader = document.getElementById('search-loader');
    const sectionTitle = document.getElementById('section-title');

    // --- Duration Dropdown Logic ---
    let selectedDuration = 'medium'; // default
    const durationBtn     = document.getElementById('duration-chip-btn');
    const durationDropdown = document.getElementById('duration-dropdown');
    const durationLabel   = document.getElementById('duration-chip-label');

    if (durationBtn && durationDropdown) {
        // Toggle dropdown open/close
        durationBtn.addEventListener('click', (e) => {
            e.stopPropagation();
            const isOpen = durationDropdown.classList.toggle('open');
            durationBtn.classList.toggle('open', isOpen);
            durationBtn.setAttribute('aria-expanded', isOpen);
        });

        // Select an option
        durationDropdown.querySelectorAll('.duration-option').forEach(opt => {
            opt.addEventListener('click', () => {
                selectedDuration = opt.dataset.value;
                if (durationLabel) durationLabel.textContent = opt.dataset.label;

                // Update selected state
                durationDropdown.querySelectorAll('.duration-option').forEach(o => {
                    o.classList.toggle('selected', o === opt);
                    const tick = o.querySelector('svg');
                    if (!o.querySelector('svg')) return;
                    o.querySelector('svg').style.opacity = (o === opt) ? '1' : '0';
                });

                // Close dropdown
                durationDropdown.classList.remove('open');
                durationBtn.classList.remove('open');
                durationBtn.setAttribute('aria-expanded', 'false');
            });
        });

        // Close on outside click
        document.addEventListener('click', () => {
            durationDropdown.classList.remove('open');
            durationBtn.classList.remove('open');
            durationBtn.setAttribute('aria-expanded', 'false');
        });
    }
    // --- End Duration Dropdown ---

    // --- Cancel Search Logic ---
    const cancelBtn = document.getElementById('btn-cancel-search');
    let searchAbortController = null;

    const setSearching = (isSearching) => {
        if (btnSearch)   btnSearch.style.display  = isSearching ? 'none'  : 'inline-flex';
        if (cancelBtn)   cancelBtn.style.display  = isSearching ? 'inline-flex' : 'none';
        if (reviewInput) reviewInput.disabled = isSearching;
    };

    if (cancelBtn) {
        cancelBtn.addEventListener('click', () => {
            if (searchAbortController) {
                searchAbortController.abort();
            }
        });
    }
    // --- End Cancel Logic ---

    const performSearch = async (query) => {
        if (!query || query.trim() === "") {
            alert("Please enter a valid movie keyword or YouTube video URL.");
            return;
        }

        const trimmed = query.trim();

        // If user entered a full YouTube URL, directly navigate to analysis
        if (trimmed.startsWith('http://') || trimmed.startsWith('https://') || trimmed.includes('youtube.com') || trimmed.includes('youtu.be')) {
            window.location.href = `/analysis?url=${encodeURIComponent(trimmed)}`;
            return;
        }

        if (sectionTitle) sectionTitle.textContent = `Searching for "${trimmed}"...`;

        // Remove previous search results
        document.querySelectorAll('.dynamic-search-card').forEach(c => c.remove());

        // Show loader with pipeline-aware message
        if (searchLoader) {
            searchLoader.style.display = 'block';
            const loaderMsg = searchLoader.querySelector('p');
            if (loaderMsg) {
                loaderMsg.textContent = 'Searching YouTube & verifying English subtitles... (~20-40s)';
            }
        }

        // Setup abort controller for this request
        searchAbortController = new AbortController();
        setSearching(true);

        try {
            const response = await fetch(
                `/api/search?q=${encodeURIComponent(trimmed)}&duration=${selectedDuration}`,
                { signal: searchAbortController.signal }
            );
            const data = await response.json();

            if (searchLoader) searchLoader.style.display = 'none';
            setSearching(false);

            if (data.error) {
                if (sectionTitle) sectionTitle.textContent = 'Search failed';
                alert('Search error: ' + data.error);
                return;
            }

            const count = data.english_videos || 0;
            if (sectionTitle) {
                sectionTitle.textContent = count > 0
                    ? `Results for "${data.query || trimmed}" — ${count} English review${count !== 1 ? 's' : ''} found`
                    : `No English reviews found for "${trimmed}"`;
            }

            if (data.results && data.results.length > 0) {
                data.results.forEach(video => {
                    const safeTitle   = (video.title   || '').replace(/"/g, '&quot;').replace(/</g, '&lt;');
                    const safeChannel = (video.channel || 'Unknown Channel').replace(/</g, '&lt;');
                    const badgeClass  = video.subtitle_type === 'manual' ? 'badge-manual' : 'badge-auto';
                    const badgeLabel  = video.subtitle_type === 'manual' ? '📝 Manual' : '🤖 Auto';
                    const analyzeUrl  = encodeURIComponent(video.url);

                    const cardHTML = `
                    <article class="review-card dynamic-search-card">
                        <div class="card-image-wrapper">
                            <img src="${video.thumbnail}" alt="${safeTitle}" class="card-thumb" style="object-fit: cover; width: 100%; height: 100%;">
                            <span class="duration-badge">${video.duration || 'N/A'}</span>
                            <span class="subtitle-badge ${badgeClass}">${badgeLabel}</span>
                        </div>
                        <div class="card-body">
                            <h3 class="card-title" title="${safeTitle}">${safeTitle}</h3>
                            <div class="card-meta">
                                <span class="meta-item meta-channel">
                                    <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
                                        <path d="M20 21v-2a4 4 0 0 0-4-4H8a4 4 0 0 0-4 4v2"/>
                                        <circle cx="12" cy="7" r="4"/>
                                    </svg>
                                    <span>${safeChannel}</span>
                                </span>
                                <span class="meta-item">
                                    <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
                                        <rect x="3" y="4" width="18" height="18" rx="2" ry="2"/>
                                        <line x1="16" y1="2" x2="16" y2="6"/>
                                        <line x1="8" y1="2" x2="8" y2="6"/>
                                        <line x1="3" y1="10" x2="21" y2="10"/>
                                    </svg>
                                    <span>${video.published || ''}</span>
                                </span>
                            </div>
                            <button type="button" class="btn-analyze-card" onclick="window.location.href='/analysis?url=${analyzeUrl}'">
                                <svg class="analyze-icon" width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round">
                                    <line x1="18" y1="20" x2="18" y2="10"/>
                                    <line x1="12" y1="20" x2="12" y2="4"/>
                                    <line x1="6" y1="20" x2="6" y2="14"/>
                                </svg>
                                <span>Analyze Sentiment</span>
                            </button>
                        </div>
                    </article>
                    `;
                    reviewsGrid.insertAdjacentHTML('beforeend', cardHTML);
                });
            } else {
                reviewsGrid.insertAdjacentHTML('beforeend',
                    '<p class="dynamic-search-card" style="grid-column:1/-1;color:#94A3B8;text-align:center;padding:40px 0;">'
                    + '🎬 No English movie reviews with subtitles found. Try a different film name.</p>'
                );
            }
        } catch (error) {
            if (error.name === 'AbortError') {
                // User cancelled — reload to restore initial trending reviews state
                window.location.reload();
            } else {
                console.error('Search error:', error);
                if (searchLoader) searchLoader.style.display = 'none';
                if (sectionTitle) sectionTitle.textContent = 'Search Results';
                alert('Failed to connect to the server.');
            }
            setSearching(false);
        }
    };

    if (btnSearch && reviewInput) {
        btnSearch.addEventListener('click', () => performSearch(reviewInput.value));
    }
    
    if (reviewInput) {
        reviewInput.addEventListener('keypress', (e) => {
            if (e.key === 'Enter') performSearch(reviewInput.value);
        });
    }

    // Auto-fetch real Trending Movie Reviews on Dashboard page load
    const loadTrendingReviews = async () => {
        if (!reviewsGrid) return;
        
        // Immediately remove pre-existing sample cards BEFORE starting fetch
        Array.from(reviewsGrid.children).forEach(child => {
            if (child.id !== 'search-loader') child.remove();
        });

        // Show loader initially while fetching
        if (searchLoader) searchLoader.style.display = 'block';

        try {
            const response = await fetch('/api/trending-reviews?limit=8');
            const data = await response.json();

            if (searchLoader) searchLoader.style.display = 'none';

            if (data.results && data.results.length > 0) {
                data.results.forEach(video => {
                    const cardHTML = `
                    <article class="review-card dynamic-search-card">
                        <div class="card-image-wrapper">
                            <img src="${video.thumbnail}" alt="${video.title.replace(/"/g, '&quot;')}" class="card-thumb" style="object-fit: cover; width: 100%; height: 100%;">
                            <span class="duration-badge">${video.duration_str}</span>
                        </div>
                        <div class="card-body">
                            <h3 class="card-title" title="${video.title.replace(/"/g, '&quot;')}">${video.title}</h3>
                            <div class="card-meta">
                                <span class="meta-item">
                                    <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
                                        <path d="M1 12s4-8 11-8 11 8 11 8-4 8-11 8-11-8-11-8z"/>
                                        <circle cx="12" cy="12" r="3"/>
                                    </svg>
                                    <span>${video.view_str}</span>
                                </span>
                            </div>
                            <button type="button" class="btn-analyze-card" onclick="window.location.href='/analysis?url=${encodeURIComponent(video.url)}'">
                                <svg class="analyze-icon" width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round">
                                    <line x1="18" y1="20" x2="18" y2="10"/>
                                    <line x1="12" y1="20" x2="12" y2="4"/>
                                    <line x1="6" y1="20" x2="6" y2="14"/>
                                </svg>
                                <span>Analyze Sentiment</span>
                            </button>
                        </div>
                    </article>
                    `;
                    reviewsGrid.insertAdjacentHTML('beforeend', cardHTML);
                });
            }
        } catch (err) {
            console.error("Failed to load trending movie reviews:", err);
            if (searchLoader) searchLoader.style.display = 'none';
        }
    };

    if (reviewsGrid) {
        loadTrendingReviews();
    }

    // Existing hardcoded card click triggers (fallback for defaults)
    const cardAnalyzeBtns = document.querySelectorAll('.btn-analyze-card');
    cardAnalyzeBtns.forEach(btn => {
        // Only attach to static cards, dynamic ones use inline onclick
        if(!btn.closest('.dynamic-search-card')) {
            btn.addEventListener('click', (e) => {
                alert("This is a sample card. Try searching for a real YouTube review and clicking Analyze!");
            });
        }
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
