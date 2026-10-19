/**
 * CineInsight Shared Account Panel Dropdown
 * Handles accessible keyboard navigation, click toggle, outside click, and avatar coloring.
 */
(() => {
    'use strict';

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

    function initAccountPanel() {
        const btn = document.getElementById('user-menu-button');
        const menu = document.getElementById('user-dropdown-menu');
        const panel = document.querySelector('.user-panel');

        // Colorize all avatar elements in this document
        document.querySelectorAll('.avatar-circle, .dropdown-avatar-circle').forEach(el => {
            const name = el.dataset.name || '';
            el.style.background = getAvatarColor(name);
        });

        if (!btn || !menu || !panel) return;

        function getMenuItems() {
            return Array.from(menu.querySelectorAll('[role="menuitem"]')).filter(el => !el.disabled);
        }

        function openMenu(focusFirst = false) {
            btn.setAttribute('aria-expanded', 'true');
            menu.hidden = false;
            menu.classList.add('open');
            if (focusFirst) {
                const items = getMenuItems();
                if (items.length > 0) {
                    items[0].focus();
                }
            }
        }

        function closeMenu(returnFocus = false) {
            if (btn.getAttribute('aria-expanded') === 'false' && menu.hidden) return;
            btn.setAttribute('aria-expanded', 'false');
            menu.hidden = true;
            menu.classList.remove('open');
            if (returnFocus) {
                btn.focus();
            }
        }

        function toggleMenu() {
            const isOpen = btn.getAttribute('aria-expanded') === 'true';
            if (isOpen) {
                closeMenu(false);
            } else {
                openMenu(false);
            }
        }

        btn.addEventListener('click', (e) => {
            e.stopPropagation();
            toggleMenu();
        });

        btn.addEventListener('keydown', (e) => {
            if (e.key === 'ArrowDown' || e.key === 'Enter' || e.key === ' ') {
                e.preventDefault();
                openMenu(true);
            } else if (e.key === 'ArrowUp') {
                e.preventDefault();
                openMenu(false);
                const items = getMenuItems();
                if (items.length > 0) items[items.length - 1].focus();
            } else if (e.key === 'Escape') {
                closeMenu(false);
            }
        });

        menu.addEventListener('keydown', (e) => {
            const items = getMenuItems();
            const currentIndex = items.indexOf(document.activeElement);

            if (e.key === 'Escape') {
                e.preventDefault();
                closeMenu(true);
            } else if (e.key === 'ArrowDown') {
                e.preventDefault();
                const nextIndex = (currentIndex + 1) % items.length;
                items[nextIndex].focus();
            } else if (e.key === 'ArrowUp') {
                e.preventDefault();
                const prevIndex = (currentIndex - 1 + items.length) % items.length;
                items[prevIndex].focus();
            } else if (e.key === 'Home') {
                e.preventDefault();
                if (items.length > 0) items[0].focus();
            } else if (e.key === 'End') {
                e.preventDefault();
                if (items.length > 0) items[items.length - 1].focus();
            } else if (e.key === 'Tab') {
                // Focus is leaving or navigating within; if leaving panel, close
                setTimeout(() => {
                    if (!panel.contains(document.activeElement)) {
                        closeMenu(false);
                    }
                }, 0);
            }
        });

        // Close on click outside
        document.addEventListener('click', (e) => {
            if (!panel.contains(e.target)) {
                closeMenu(false);
            }
        });

        // Close on focus moving outside panel
        document.addEventListener('focusin', (e) => {
            if (!panel.contains(e.target)) {
                closeMenu(false);
            }
        });
    }

    if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', initAccountPanel);
    } else {
        initAccountPanel();
    }
})();
