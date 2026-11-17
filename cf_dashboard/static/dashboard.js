const FONT = "'JetBrains Mono', monospace";
const TEXT_DIM = "#8b96a5";
const GRID = "rgba(139, 150, 165, 0.12)";

Chart.defaults.font.family = FONT;
Chart.defaults.color = TEXT_DIM;

async function getJSON(url) {
  const res = await fetch(url);
  if (!res.ok) throw new Error(`${url} -> ${res.status}`);
  return res.json();
}

function baseGrid(axis) {
  return {
    grid: { color: GRID, drawTicks: false },
    border: { display: false },
    ticks: { color: TEXT_DIM, font: { size: 11 } },
  };
}

// ---------- summary strip ----------

async function renderSummary() {
  const el = document.getElementById("summary-stats");
  try {
    const s = await getJSON("/api/summary");
    if (!s.total) {
      el.innerHTML = `<span class="stat">no rated problems in the DB yet — run a scrape first</span>`;
      return;
    }
    el.innerHTML = `
      <span class="stat"><strong>${s.total}</strong> problems</span>
      <span class="stat"><strong>${s.min_rating}–${s.max_rating}</strong> rating range</span>
      <span class="stat"><strong>${s.avg_rating}</strong> avg rating</span>
      <span class="stat"><strong>${s.tag_count}</strong> distinct tags</span>
    `;
  } catch (e) {
    el.innerHTML = `<span class="stat">couldn't reach the API — is the Mongo connection working?</span>`;
  }
}

// ---------- hero: tag lifespan (floating range bars) ----------

async function renderLifespan() {
  const rows = await getJSON("/api/tag-lifespan");
  const ctx = document.getElementById("chart-lifespan");
  if (!rows.length) return;

  new Chart(ctx, {
    type: "bar",
    data: {
      labels: rows.map(r => r.tag),
      datasets: [{
        data: rows.map(r => [r.min, r.max]),
        backgroundColor: rows.map(r => r.color + "cc"),
        borderRadius: 3,
        barThickness: 16,
      }],
    },
    options: {
      indexAxis: "y",
      responsive: true,
      maintainAspectRatio: false,
      plugins: {
        legend: { display: false },
        tooltip: {
          callbacks: {
            label: (item) => {
              const r = rows[item.dataIndex];
              return `${r.min}–${r.max} · avg ${r.avg} · ${r.count} problems`;
            },
          },
        },
      },
      scales: {
        x: { ...baseGrid(), title: { display: true, text: "rating", color: TEXT_DIM, font: { size: 11 } } },
        y: { grid: { display: false }, border: { display: false }, ticks: { color: "#e6edf3", font: { size: 11.5 } } },
      },
    },
  });
}

// ---------- rating histogram ----------

async function renderHistogram() {
  const d = await getJSON("/api/rating-histogram");
  const ctx = document.getElementById("chart-histogram");
  if (!d.labels.length) return;

  new Chart(ctx, {
    type: "bar",
    data: {
      labels: d.labels,
      datasets: [{ data: d.counts, backgroundColor: d.colors.map(c => c + "cc"), borderRadius: 3 }],
    },
    options: {
      responsive: true,
      maintainAspectRatio: false,
      plugins: { legend: { display: false } },
      scales: {
        x: { ...baseGrid(), ticks: { color: TEXT_DIM, font: { size: 10 }, maxRotation: 0, autoSkip: true } },
        y: { ...baseGrid(), beginAtZero: true },
      },
    },
  });
}

// ---------- tag mix by band (stacked) ----------

async function renderBands() {
  const d = await getJSON("/api/tag-by-band");
  const ctx = document.getElementById("chart-bands");
  if (!d.series.length) return;

  const palette = ["#4fd1c5", "#e08a1e", "#a83fd9", "#2b5fd9", "#17a2a2", "#1fa34a", "#e03e3e", "#8f8f8f"];

  new Chart(ctx, {
    type: "bar",
    data: {
      labels: d.bands,
      datasets: d.series.map((s, i) => ({
        label: s.tag,
        data: s.values,
        backgroundColor: palette[i % palette.length] + "cc",
        borderRadius: 2,
      })),
    },
    options: {
      responsive: true,
      maintainAspectRatio: false,
      plugins: {
        legend: {
          position: "bottom",
          labels: { color: TEXT_DIM, font: { size: 10 }, boxWidth: 10, boxHeight: 10, padding: 10 },
        },
      },
      scales: {
        x: { ...baseGrid(), stacked: true, ticks: { color: TEXT_DIM, font: { size: 10 } } },
        y: { ...baseGrid(), stacked: true, beginAtZero: true },
      },
    },
  });
}

// ---------- co-occurrence heatmap (custom, no plugin needed) ----------

function heatColor(value, max) {
  if (value === 0) return "rgba(139, 150, 165, 0.06)";
  const t = Math.min(value / max, 1);
  // interpolate from dim teal to bright teal
  const alpha = 0.15 + t * 0.75;
  return `rgba(79, 209, 197, ${alpha.toFixed(2)})`;
}

async function renderCooccurrence() {
  const d = await getJSON("/api/tag-cooccurrence");
  const el = document.getElementById("heatmap");
  if (!d.tags.length) return;

  const n = d.tags.length;
  el.style.gridTemplateColumns = `90px repeat(${n}, 1fr)`;
  el.innerHTML = "";

  // header row
  const headerRow = document.createElement("div");
  headerRow.className = "heatmap__row";
  headerRow.style.gridColumn = `1 / -1`;
  el.style.display = "grid";
  el.style.gridTemplateRows = `repeat(${n + 1}, minmax(20px, 1fr))`;

  const corner = document.createElement("div");
  el.appendChild(corner);
  d.tags.forEach(t => {
    const label = document.createElement("div");
    label.className = "heatmap__label";
    label.textContent = t;
    label.style.writingMode = "vertical-rl";
    label.style.transform = "rotate(180deg)";
    label.style.justifyContent = "center";
    el.appendChild(label);
  });

  d.tags.forEach((rowTag, i) => {
    const label = document.createElement("div");
    label.className = "heatmap__label";
    label.textContent = rowTag;
    el.appendChild(label);

    d.matrix[i].forEach((value, j) => {
      const cell = document.createElement("div");
      cell.className = "heatmap__cell";
      cell.style.background = heatColor(value, d.max);
      cell.textContent = value > 0 ? value : "";
      cell.title = `${rowTag} × ${d.tags[j]}: ${value}`;
      el.appendChild(cell);
    });
  });
}

// ---------- LLM vs official tag agreement ----------

async function renderAgreement() {
  const d = await getJSON("/api/tag-agreement");
  const ctx = document.getElementById("chart-agreement");
  if (!d.bands.length) return;

  new Chart(ctx, {
    type: "line",
    data: {
      labels: d.bands,
      datasets: [{
        data: d.agreement_pct,
        borderColor: "#4fd1c5",
        backgroundColor: "rgba(79, 209, 197, 0.15)",
        fill: true,
        tension: 0.35,
        spanGaps: true,
        pointRadius: 4,
        pointBackgroundColor: "#4fd1c5",
      }],
    },
    options: {
      responsive: true,
      maintainAspectRatio: false,
      plugins: { legend: { display: false } },
      scales: {
        x: { ...baseGrid() },
        y: { ...baseGrid(), min: 0, max: 100, ticks: { color: TEXT_DIM, callback: (v) => v + "%" } },
      },
    },
  });
}

renderSummary();
renderLifespan();
renderHistogram();
renderBands();
renderCooccurrence();
renderAgreement();

// ===============================
// Practice Problem Generator
// ===============================

async function loadPracticeTags() {
    const response = await fetch("/api/tags");
    const tags = await response.json();

    const tagSelect = document.getElementById("tag-filter");

    tags.forEach(tag => {
        const option = document.createElement("option");
        option.value = tag;
        option.textContent = tag;
        tagSelect.appendChild(option);
    });
}

loadPracticeTags();



async function generatePracticeSet() {
    const minRating = document.getElementById("min-rating").value;
    const maxRating = document.getElementById("max-rating").value;
    const mode = document.getElementById("tag-mode").value;
    const limit = document.getElementById("problem-limit").value;

    const selectedTags = Array.from(
        document.getElementById("tag-filter").selectedOptions
    )
        .map(option => option.value)
        .filter(Boolean);

    const params = new URLSearchParams({
        min_rating: minRating,
        max_rating: maxRating,
        tags: selectedTags.join(","),
        mode: mode,
        limit: limit
    });

    const results = document.getElementById("practice-results");

    results.innerHTML = "<p>Generating practice set...</p>";

    try {
        const response = await fetch(`/api/practice-problems?${params}`);

        if (!response.ok) {
            throw new Error("API request failed");
        }

        const data = await response.json();

        if (!data.problems.length) {
            results.innerHTML = `
                <p class="practice-empty">
                    No problems found for these filters.
                </p>
            `;
            return;
        }

        results.innerHTML = `
            <div class="practice-count">
                ${data.count} matching problems found
            </div>

            <div class="problem-list">
                ${data.problems.map((problem, index) => `
                    <div class="problem-row">

                        <div class="problem-number">
                            ${index + 1}
                        </div>

                        <div class="problem-info">
                            <div class="problem-title">
                                ${escapeHtml(problem.title)}
                            </div>

                            <div class="problem-tags">
                                ${problem.tags.map(tag => `
                                    <span class="tag">
                                        ${escapeHtml(tag)}
                                    </span>
                                `).join("")}
                            </div>
                        </div>

                        <div class="problem-rating">
                            ${problem.rating}
                        </div>

                    </div>
                `).join("")}
            </div>
        `;

    } catch (error) {
        console.error(error);

        results.innerHTML = `
            <p class="practice-error">
                Couldn't load practice problems.
            </p>
        `;
    }
}


function escapeHtml(value) {
    const div = document.createElement("div");
    div.textContent = value;
    return div.innerHTML;
}


document
    .getElementById("generate-practice")
    ?.addEventListener("click", generatePracticeSet);