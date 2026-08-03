/**
 * CineInsight Profile Page JavaScript
 * - Avatar initials color generator (consistent palette)
 */

document.addEventListener('DOMContentLoaded', () => {

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

    // Apply to large profile avatar
    const profileAvatar = document.getElementById('profile-avatar');
    if (profileAvatar) {
        profileAvatar.style.background = getAvatarColor(profileAvatar.dataset.name || '');
    }

    // Apply to header avatar circle
    document.querySelectorAll('.avatar-circle').forEach(avatar => {
        avatar.style.background = getAvatarColor(avatar.dataset.name || '');
    });

});
