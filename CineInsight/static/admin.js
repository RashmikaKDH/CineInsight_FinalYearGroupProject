/**
 * CineInsight Admin Panel JavaScript
 * - Live user search/filter
 * - Delete confirmation modal
 * - Avatar initials color generator
 */

document.addEventListener('DOMContentLoaded', () => {

    // ── Avatar Color Generator ────────────────────────────────────────────
    // Deterministic color based on first char of name
    const AVATAR_COLORS = [
        'linear-gradient(135deg, #FDBA74, #E35614)',  // orange
        'linear-gradient(135deg, #93C5FD, #2563EB)',  // blue
        'linear-gradient(135deg, #86EFAC, #16A34A)',  // green
        'linear-gradient(135deg, #F9A8D4, #DB2777)',  // pink
        'linear-gradient(135deg, #C4B5FD, #7C3AED)',  // purple
        'linear-gradient(135deg, #FDE68A, #D97706)',  // amber
        'linear-gradient(135deg, #6EE7B7, #059669)',  // teal
        'linear-gradient(135deg, #FCA5A5, #DC2626)',  // red
    ];

    function getAvatarColor(name) {
        if (!name) return AVATAR_COLORS[0];
        const index = name.charCodeAt(0) % AVATAR_COLORS.length;
        return AVATAR_COLORS[index];
    }

    // Apply colors to all table avatars
    document.querySelectorAll('.table-avatar').forEach(avatar => {
        const name = avatar.dataset.name || '';
        avatar.style.background = getAvatarColor(name);
    });

    // Apply color to header avatar circle
    document.querySelectorAll('.avatar-circle').forEach(avatar => {
        const name = avatar.dataset.name || '';
        avatar.style.background = getAvatarColor(name);
    });


    // ── Live Search / Filter ──────────────────────────────────────────────
    const searchInput = document.getElementById('admin-search-input');
    const clearBtn = document.getElementById('search-clear-btn');
    const noResults = document.getElementById('no-search-results');
    const searchTermDisplay = document.getElementById('search-term-display');
    const userRows = document.querySelectorAll('.user-row');
    const userCountEl = document.getElementById('user-count');

    if (searchInput) {
        searchInput.addEventListener('input', () => {
            const query = searchInput.value.trim().toLowerCase();

            if (clearBtn) {
                clearBtn.style.display = query ? 'flex' : 'none';
            }

            let visibleCount = 0;

            userRows.forEach(row => {
                const name = (row.dataset.name || '').toLowerCase();
                const email = (row.dataset.email || '').toLowerCase();
                const matches = name.includes(query) || email.includes(query);
                row.style.display = matches ? '' : 'none';
                if (matches) visibleCount++;
            });

            // Show/hide no-results message
            if (noResults && searchTermDisplay) {
                if (query && visibleCount === 0) {
                    searchTermDisplay.textContent = query;
                    noResults.style.display = 'flex';
                } else {
                    noResults.style.display = 'none';
                }
            }

            // Update counter
            if (userCountEl) {
                userCountEl.textContent = visibleCount;
            }
        });
    }

    if (clearBtn) {
        clearBtn.addEventListener('click', () => {
            searchInput.value = '';
            clearBtn.style.display = 'none';
            userRows.forEach(row => row.style.display = '');
            if (noResults) noResults.style.display = 'none';
            if (userCountEl) userCountEl.textContent = userRows.length;
            searchInput.focus();
        });
    }


    // ── Delete Confirmation Modal ─────────────────────────────────────────
    const modal = document.getElementById('delete-modal');
    const deleteForm = document.getElementById('delete-form');
    const modalUserName = document.getElementById('modal-user-name');

    // Close modal when clicking outside the card
    if (modal) {
        modal.addEventListener('click', (e) => {
            if (e.target === modal) closeDeleteModal();
        });
    }

    // Close on Escape key
    document.addEventListener('keydown', (e) => {
        if (e.key === 'Escape' && modal && modal.style.display !== 'none') {
            closeDeleteModal();
        }
    });

    // Auto-dismiss flash messages after 5 seconds
    const flashMessages = document.querySelectorAll('.flash-message');
    flashMessages.forEach(msg => {
        setTimeout(() => {
            msg.style.transition = 'opacity 0.4s ease, transform 0.4s ease';
            msg.style.opacity = '0';
            msg.style.transform = 'translateY(-8px)';
            setTimeout(() => msg.remove(), 400);
        }, 5000);
    });

});


/**
 * Open the delete confirmation modal.
 * @param {number} userId - The user's database ID.
 * @param {string} userName - The user's display name.
 */
function openDeleteModal(userId, userName) {
    const modal = document.getElementById('delete-modal');
    const deleteForm = document.getElementById('delete-form');
    const modalUserName = document.getElementById('modal-user-name');

    if (!modal || !deleteForm || !modalUserName) return;

    // Set the form action to the correct delete route
    deleteForm.action = `/admin/delete/${userId}`;
    modalUserName.textContent = userName;

    // Show modal
    modal.style.display = 'flex';
    document.body.style.overflow = 'hidden';

    // Focus the cancel button for keyboard accessibility
    const cancelBtn = document.getElementById('modal-cancel-btn');
    if (cancelBtn) setTimeout(() => cancelBtn.focus(), 50);
}


/**
 * Close the delete confirmation modal without deleting.
 */
function closeDeleteModal() {
    const modal = document.getElementById('delete-modal');
    if (modal) {
        modal.style.display = 'none';
        document.body.style.overflow = '';
    }
}
