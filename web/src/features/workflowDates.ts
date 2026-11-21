export function indiaDateKey(date = new Date()): string {
  const parts = new Intl.DateTimeFormat("en-GB", {
    timeZone: "Asia/Kolkata", year: "numeric", month: "2-digit", day: "2-digit",
  }).formatToParts(date);
  const part = (type: Intl.DateTimeFormatPartTypes) => parts.find(item => item.type === type)!.value;
  return `${part("year")}-${part("month")}-${part("day")}`;
}

export function workflowScope(section: "start" | "workday" | "eod" | "eom" | "eoy", day: string): string {
  if (section === "eom") return day.slice(0, 7);
  if (section === "eoy") {
    const year = Number(day.slice(0, 4));
    return `fy-${Number(day.slice(5, 7)) >= 4 ? year : year - 1}`;
  }
  return day;
}
