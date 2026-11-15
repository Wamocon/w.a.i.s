import { Fragment } from "react";
import { ANZEIGENAME } from "@/lib/anzeigename";

/** Buchstaben des Namens ohne Punkte: "W.A.I.S." ergibt W, A, I, S */
const BUCHSTABEN = ANZEIGENAME.split(".").filter(Boolean);

/** Der Name in der Markenschrift, jeder Punkt ein eigener Span */
function Name() {
  return (
    <span className="marke">
      {BUCHSTABEN.map((buchstabe, i) => (
        <Fragment key={i}>
          {buchstabe}
          <span className="marke-punkt">.</span>
        </Fragment>
      ))}
    </span>
  );
}

/**
 * Wortmarke: der Name W.A.I.S. in der Markenschrift (Klasse .marke in globals.css, Cormorant Garamond 600), die vier Punkte
 * in WMC-Rot (.marke-punkt). Größe und Zeilenhöhe kommen von der Stelle, an der sie steht.
 * Mit `text` (Laborkonten: "W.A.I.S. Testlabor, Platz 3") steht nur der Name am Anfang in der Markenschrift, der Zusatz behält
 * die Schrift der Stelle. Beides steckt dann in einem Span, damit der Abstand einer Flex-Stelle nicht zwischen Name und Zusatz
 * fällt. Der Text bleibt derselbe, Screenreader lesen "W.A.I.S." wie vorher.
 */
export function Wortmarke({ text = ANZEIGENAME }: { text?: string }) {
  if (!text.startsWith(ANZEIGENAME)) return <span>{text}</span>;
  const zusatz = text.slice(ANZEIGENAME.length);
  if (!zusatz) return <Name />;
  return (
    <span>
      <Name />
      {zusatz}
    </span>
  );
}
