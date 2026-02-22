// DevTracker frontend helpers
// Keeps backend unchanged

(function () {
  const qs = (sel) => document.querySelector(sel);
  const qsa = (sel) => Array.from(document.querySelectorAll(sel));

  // ============================================================
  // INTAKE FORM
  // ============================================================

  const intakeForm = qs('#intakeForm');

  if (intakeForm) {
    const teamList = qs('#teamList');
    const addMemberBtn = qs('#addMemberBtn');
    const formError = qs('#formError');
    const formStatus = qs('#formStatus');
    const submitBtn = qs('#submitBtn');

    function showError(msg) {
      if (!formError) return alert(msg);
      formError.textContent = msg;
      formError.classList.remove('d-none');
    }

    function clearError() {
      if (!formError) return;
      formError.textContent = '';
      formError.classList.add('d-none');
    }

    function memberRow(role = 'BE', seniority = 'MID') {
      const row = document.createElement('div');
      row.className = 'd-flex gap-2 align-items-center';

      row.innerHTML = `
        <select class="form-select form-select-sm w-auto" data-role>
          <option value="FE">FE</option>
          <option value="BE">BE</option>
          <option value="DEVOPS">DEVOPS</option>
        </select>
        <select class="form-select form-select-sm w-auto" data-seniority>
          <option value="JUNIOR">JUNIOR</option>
          <option value="MID">MID</option>
          <option value="SENIOR">SENIOR</option>
        </select>
        <button type="button" class="btn btn-sm btn-outline-danger" data-remove>Remove</button>
      `;

      row.querySelector('[data-role]').value = role;
      row.querySelector('[data-seniority]').value = seniority;

      row.querySelector('[data-remove]').addEventListener('click', () => {
        row.remove();
        row.querySelector('[data-remove]').addEventListener('click', () => {
          row.remove();
        });
      });

      return row;
    }

    function addDefaultTeam() {
      teamList.appendChild(memberRow('BE', 'MID'));
      teamList.appendChild(memberRow('FE', 'MID'));
    }

    addMemberBtn?.addEventListener('click', () => {
      teamList.appendChild(memberRow());
    });

    if (teamList && teamList.children.length === 0) {
      addDefaultTeam();
    }

    function readTechStack() {
      const checked = qsa('input[type="checkbox"][id^="stack"]:checked')
        .map((el) => el.value);

      const extra = (qs('#stackExtra')?.value || '')
        .split(',')
        .map((s) => s.trim())
        .filter(Boolean);

      return Array.from(new Set([...checked, ...extra]));
    }

    function readTeam() {
      return Array.from(teamList.children).map((row) => ({
        role: row.querySelector('[data-role]').value,
        seniority: row.querySelector('[data-seniority]').value,
      }));
    }

    intakeForm.addEventListener('submit', async (e) => {
      e.preventDefault();
      clearError();

      const title = (qs('#title')?.value || '').trim();
      const description = (qs('#description')?.value || '').trim();
      const deadline = (qs('#deadline')?.value || '').trim();

      if (!title) return showError("Please enter a project title.");
      if (!deadline) return showError("Please choose a deadline date.");
      if (teamList.children.length === 0) {
        showError("Add at least one team member.");
        return;
      }

      const payload = {
        title,
        description,
        tech_stack: readTechStack(),
        deadline,
        team: readTeam(),
      };

      submitBtn.disabled = true;
      formStatus.textContent = 'Estimating...';

      try {
        const resp = await fetch('/api/intake/', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify(payload),
        });

        const data = await resp.json();
        if (!resp.ok || !data.ok) throw new Error(data.error || 'Request failed');

        window.location.href = `/projects/${data.project_id}/`;
      } catch (err) {
        showError(err.message);
      } finally {
        submitBtn.disabled = false;
        formStatus.textContent = '';
      }
    });
  }

  // ============================================================
  // DELETE PROJECT
  // ============================================================

  qsa('[data-delete-project]').forEach((btn) => {
    btn.addEventListener('click', async () => {
      const id = btn.dataset.deleteProject;
      const title = btn.dataset.deleteTitle || 'this project';

      if (!confirm(`Delete "${title}"? This cannot be undone.`)) return;

      btn.disabled = true;

      try {
        const resp = await fetch(`/api/project/${id}/`, {
          method: 'DELETE',
        });

        const data = await resp.json();
        if (!resp.ok || !data.ok) throw new Error(data.error || 'Delete failed');

        if (window.location.pathname.startsWith('/projects/')) {
          window.location.href = '/dashboard/';
        } else {
          location.reload();
        }
      } catch (err) {
        alert(err.message);
        btn.disabled = false;
      }
    });
  });

  // ============================================================
  // EDIT PROJECT
  // ============================================================

  const editForm = qs('#editProjectForm');

  if (editForm) {
    const id = editForm.dataset.projectId;
    const saveBtn = qs('#editSaveBtn');

    editForm.addEventListener('submit', async (e) => {
      e.preventDefault();

      const payload = {
        title: qs('#editTitle')?.value.trim(),
        description: qs('#editDescription')?.value.trim(),
        deadline: qs('#editDeadline')?.value.trim(),
        tech_stack: (qs('#editTechStack')?.value || '')
          .split(',')
          .map((s) => s.trim())
          .filter(Boolean),
      };

      saveBtn.disabled = true;

      try {
        const resp = await fetch(`/api/project/${id}/`, {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify(payload),
        });

        const data = await resp.json();
        if (!resp.ok || !data.ok) throw new Error(data.error || 'Save failed');

        location.reload();
      } catch (err) {
        alert(err.message);
      } finally {
        saveBtn.disabled = false;
      }
    });
  }

})();