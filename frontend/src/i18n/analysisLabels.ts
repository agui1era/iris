import type { Language } from "./context";

const EVENT_LABELS: Record<string, [string, string]> = {
  none: ["Sin eventos", "No event"],
  no_event: ["Sin eventos", "No event"],
  no_events: ["Sin eventos", "No events"],
  possible_fall: ["Posible caída", "Possible fall"],
  fall: ["Caída", "Fall"],
  person_fallen: ["Persona caída", "Person fallen"],
  person_on_floor: ["Persona en el suelo", "Person on the floor"],
  unusual_posture: ["Postura inusual", "Unusual posture"],
  obstacle: ["Obstáculo detectado", "Obstacle detected"],
  assistance_needed: ["Asistencia necesaria", "Assistance needed"],
};

export function analysisEventLabel(value: string, language: Language): string {
  const normalized = value.trim().toLowerCase().replace(/[\s-]+/g, "_");
  const known = EVENT_LABELS[normalized];
  if (known) return language === "es" ? known[0] : known[1];

  // Unknown machine-style values are still made readable without changing
  // the original value stored by the API.
  return value.includes("_") ? value.replaceAll("_", " ") : value;
}

const MESSAGE_LABELS: Record<string, [string, string]> = {
  "no event": ["No se detectaron eventos.", "No event detected."],
  "no events": ["No se detectaron eventos.", "No events detected."],
  "no event detected": ["No se detectaron eventos.", "No event detected."],
  "no events detected": ["No se detectaron eventos.", "No events detected."],
  "no action required": ["No se requiere ninguna acción.", "No action required."],
};

export function analysisMessageLabel(value: string, language: Language): string {
  const normalized = value.trim().toLowerCase().replace(/[.!]+$/, "");
  const known = MESSAGE_LABELS[normalized];
  return known ? (language === "es" ? known[0] : known[1]) : value;
}
