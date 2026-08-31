// 共享侧边栏（驾驶舱指令区）：传入当前页 key 渲染高亮
function renderSidebar(active) {
  const items = [
    { key: 'positions', label: '岗位库', icon: '▦', href: 'index.html', badge: '<span class="nav-badge">2</span>' },
    { key: 'dict', label: '能力词典', icon: '◈', href: 'dict.html' },
    { key: 'users', label: '用户管理', icon: '◔', href: 'users.html' },
  ];
  return `
  <aside class="sidebar">
    <div class="side-brand">
      <div class="brand-mark">测</div>
      <div>
        <div class="brand-name">胜任力测评</div>
        <div class="brand-sub">建模工作台</div>
      </div>
    </div>
    <div class="side-section">建模流程</div>
    <nav class="side-nav">
      ${items.map(i => `
        <a class="nav-item ${i.key === active ? 'active' : ''}" href="${i.href}">
          <span class="icon">${i.icon}</span>${i.label}${i.badge || ''}
        </a>`).join('')}
    </nav>
    <div class="side-user">
      <div class="avatar">A</div>
      <div>
        <div class="user-name">admin</div>
        <div class="user-role">管理员</div>
      </div>
      <span class="logout">退出</span>
    </div>
  </aside>`;
}
