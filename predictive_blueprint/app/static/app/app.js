// DevTracker frontend helpers
// Keeps backend unchanged: posts JSON to /api/intake/ and redirects to /projects/<id>/

(function () {
  const qs = (sel) => document.querySelector(sel);
  const qsa = (sel) => Array.from(document.querySelectorAll(sel));

  const intakeForm = qs('#intakeForm');
  if (!intakeForm) return; // Only run on pages that have the intake form

  const teamList = qs('#teamList');
  const addMemberBtn = qs('#addMemberBtn');
  const formError = qs('#formError');
  const formStatus = qs('#formStatus');
  const submitBtn = qs('#submitBtn');

  function showError(msg) {
    formError.textContent = msg;
    formError.classList.remove('d-none');
  }
  function clearError() {
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
      if (teamList.children.length === 0) addDefaultTeam();
    });

    return row;
  }

  function addDefaultTeam() {
    // Reasonable default to demo the app
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
    const checked = qsa('input[type="checkbox"][id^="stack"]:checked').map((el) => el.value);
    const extra = (qs('#stackExtra')?.value || '')
      .split(',')
      .map((s) => s.trim())
      .filter(Boolean);
    // de-dupe
    return Array.from(new Set([...checked, ...extra]));
  }

  function readTeam() {
    const rows = Array.from(teamList.children);
    return rows.map((row) => {
      return {
        role: row.querySelector('[data-role]').value,
        seniority: row.querySelector('[data-seniority]').value,
      };
    });
  }

  intakeForm.addEventListener('submit', async (e) => {
    e.preventDefault();
    clearError();

    const title = (qs('#title')?.value || '').trim();
    const description = (qs('#description')?.value || '').trim();
    const deadline = (qs('#deadline')?.value || '').trim();

    if (!title) return showError("Please enter a project title.");
    if (!deadline) return showError("Please choose a deadline date.");

    const payload = {
      title,
      description,
      tech_stack: readTechStack(),
      deadline,
      team: readTeam(),
    };

    submitBtn.disabled = true;
    formStatus.textContent = 'Estimating…';

    try {
      const resp = await fetch('/api/intake/', {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
        },
        body: JSON.stringify(payload),
      });

      const data = await resp.json().catch(() => null);
      if (!data || !resp.ok || !data.ok) {
        throw new Error((data && data.error) ? data.error : 'Request failed');
      }

      window.location.href = `/projects/${data.project_id}/`;
    } catch (err) {
      showError(err?.message || 'Something went wrong');
    } finally {
      submitBtn.disabled = false;
      formStatus.textContent = '';
    }
  });
})();
