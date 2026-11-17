"use client";

import { memo } from "react";
import { useUntertitel } from "@/lib/einstellungen";
import { useNutzer } from "@/lib/nutzer";
import { istLaborKonto } from "@/lib/stillStart";
import { useSelect } from "@/lib/store";
import { istOnline, nutzerZeileLeer, wamo } from "@/lib/wamo";

/** Hinweissatz in der Mitte, solange im Gespräch noch nichts zu sehen ist: wie man startet und dass man einfach sprechen kann. */
function Hinweis({ online }: { online: boolean }) {
  return <p className="caption-hint">{online ? "Sag einfach, was du brauchst." : "Tippe auf „Gespräch starten“."}</p>;
}

/**
 * Live-Untertitel (Karaoke): der aktuelle WAMO-Satz groß, gesprochene Wörter in Tinte, kommende
 * grau. Nach einer Unterbrechung bleibt der ungesagte Rest 2 s durchgestrichen stehen. Am Zugende
 * blendet der Untertitel nach 4 s auf 60 % ab. Darüber die Nutzerzeile mit dem Profilnamen,
 * Zwischenstände kursiv. Nur diese Komponente rendert im Worttakt neu.
 * Der WAMO-Text ist aria-hidden: Ton und Verlauf (role="log") tragen den Inhalt.
 */
const Untertitel = memo(function Untertitel() {
  const c = useSelect(wamo, (s) => s.caption);
  const who = useSelect(wamo, (s) => s.profil?.name.split(/\s+/)[0] ?? "Du");
  const online = useSelect(wamo, istOnline);
  const user = `${c.userDone} ${c.userLive}`.trim();
  let n = 0;

  return (
    <div className="caption" data-ended={c.turnEnd || undefined}>
      {user ? (
        <p className="caption-user" data-final={!c.userLive || undefined}>
          <b>{who}:</b> {c.userDone}
          {c.userLive && <i> {c.userLive}</i>}
        </p>
      ) : (
        !c.text && <Hinweis online={online} />
      )}
      {c.text && (
        <p className="caption-bot" aria-hidden="true" data-cut={c.interrupted || undefined}>
          <span className="caption-inner">
            {c.text.split(/(\s+)/).map((part, i) =>
              /^\s+$/.test(part) ? part : (
                <span key={i} data-spoken={n++ < c.spoken || undefined}>
                  {part}
                </span>
              ),
            )}
          </span>
        </p>
      )}
    </div>
  );
});

/**
 * Untertitel aus (der Standard, lib/untertitel.ts): kein Text aus dem Gespräch, nur der Hinweissatz, solange noch nichts gesagt ist. Der
 * Platz bleibt, damit der Kern beim Umschalten nicht springt. Abonniert nur einen Wahrheitswert, rendert also nicht im Worttakt.
 */
const NurHinweis = memo(function NurHinweis() {
  const online = useSelect(wamo, istOnline);
  const still = useSelect(wamo, (s) => nutzerZeileLeer(s.caption) && !s.caption.text);
  return (
    <div className="caption" data-aus="true">
      {still && <Hinweis online={online} />}
    </div>
  );
});

/**
 * Bereich unter dem Kern: die Live-Untertitel, wenn die Person sie in den Einstellungen (Darstellung) eingeschaltet hat, sonst nur der
 * Hinweissatz. Standard aus: Die Untertitel zeigen sofort, was das Mikrofon hört, auch Sätze einer fremden Stimme, die der Kern danach
 * verwirft; im Chat links erscheinen nur Sätze nach der Stimmprüfung (lib/stimmFilter.ts). Laborkonten behalten die Untertitel wie
 * bisher: Ihre Sitzungen haben keine Stimmprüfung, und den Abschnitt Darstellung gibt es für sie nicht (lib/laborPlatz.ts).
 */
export const LiveCaption = memo(function LiveCaption() {
  const { id, email } = useNutzer();
  const an = useUntertitel(id) || istLaborKonto(email);
  return an ? <Untertitel /> : <NurHinweis />;
});
