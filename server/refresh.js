let revision = document.querySelector('meta[name="revision"]').content;
let active;

async function follow(signal) {
    while (!signal.aborted) {
        try {
            const poll = await fetch("/changes?since=" + revision, {signal, cache: "no-store"});
            if (!poll.ok) throw new Error("refresh unavailable");
            if ((await poll.text()) === revision) continue;
            const response = await fetch(location.href, {signal, cache: "no-store"});
            if (!response.ok) throw new Error("page unavailable");
            const next = new DOMParser().parseFromString(await response.text(), "text/html");
            if (signal.aborted) return;
            const confirmation = document.querySelector("#logs details[open]");
            if (confirmation) next.querySelector("#logs details").replaceWith(confirmation);
            for (const id of ["state", "delivery", "logs"]) {
                document.getElementById(id).replaceWith(next.getElementById(id));
            }
            const csrf = next.querySelector('form[action="/key"] [name="csrf"]').value;
            document.querySelectorAll('[name="csrf"]').forEach(field => field.value = csrf);
            revision = next.querySelector('meta[name="revision"]').content;
        } catch (error) {
            if (signal.aborted) return;
            await new Promise(resolve => setTimeout(resolve, 5000));
        }
    }
}

function observe() {
    active?.abort();
    if (!document.hidden) {
        active = new AbortController();
        follow(active.signal);
    }
}
document.addEventListener("visibilitychange", observe);
window.addEventListener("pageshow", observe);
window.addEventListener("pagehide", () => active?.abort());
