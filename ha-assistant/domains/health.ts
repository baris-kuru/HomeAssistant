import {
  calcStreak,
  loadFood,
  loadHabits,
  loadHealth,
  loadProfile,
  nowTime,
  ok,
  saveFood,
  saveHabits,
  saveHealth,
  today,
} from "../shared";

export function registerHealthDomain(api: any) {
  api.registerTool({
    name: "ha_health",
    label: "Health",
    description: "Broker for health actions. Actions: log_meal, get_food_diary, delete_food_entry, log_weight, get_weight_history, log_workout, get_workout_history, log_water, define_habit, log_habit, get_habit_stats.",
    parameters: {
      type: "object",
      properties: {
        action: { type: "string" },
        args: { type: "object" },
      },
      required: ["action"],
    },
    execute: async (_id: string, params: any) => {
      const action = params.action;
      const args = params.args ?? {};
      if (!args.user_id) return ok("ha_health actions require user_id.");

      if (action === "log_meal") {
        if (!args.meal || args.calories == null) return ok("log_meal requires meal and calories.");
        const entries = loadFood(args.user_id);
        const hour = new Date().getHours();
        const mealType = args.meal_type ?? (hour < 11 ? "breakfast" : hour < 15 ? "lunch" : hour < 19 ? "dinner" : "snack");
        entries.push({ id: Date.now().toString(36), meal: args.meal, calories: args.calories, meal_type: mealType, date: today(), time: nowTime(), notes: args.notes });
        saveFood(args.user_id, entries);
        const todayTotal = entries.filter((entry) => entry.date === today()).reduce((sum, entry) => sum + entry.calories, 0);
        const goal = loadProfile(args.user_id).calorie_goal;
        let msg = `Logged ${mealType}: ${args.meal} — ${args.calories} kcal. Today's total: ${todayTotal} kcal.`;
        if (goal) {
          const pct = Math.round((todayTotal / goal) * 100);
          msg += ` (${pct}% of ${goal} kcal goal)`;
        }
        return ok(msg);
      }

      if (action === "get_food_diary") {
        const entries = loadFood(args.user_id);
        if (!entries.length) return ok("No food diary entries yet.");
        if (args.days) {
          const cutoff = new Date();
          cutoff.setDate(cutoff.getDate() - args.days);
          const recent = entries.filter((entry) => entry.date >= cutoff.toISOString().slice(0, 10));
          if (!recent.length) return ok(`No entries in the last ${args.days} days.`);
          const byDate: Record<string, typeof entries> = {};
          for (const entry of recent) (byDate[entry.date] ??= []).push(entry);
          const lines: string[] = [];
          for (const [date, dayEntries] of Object.entries(byDate).sort()) {
            const total = dayEntries.reduce((sum, entry) => sum + entry.calories, 0);
            lines.push(`\n${date} — ${total} kcal`);
            for (const entry of dayEntries) lines.push(`  ${entry.time} [${entry.meal_type}] ${entry.meal}: ${entry.calories} kcal`);
          }
          return ok(lines.join("\n").trim());
        }
        const date = args.date ?? today();
        const dayEntries = entries.filter((entry) => entry.date === date);
        if (!dayEntries.length) return ok(`No entries for ${date}.`);
        const total = dayEntries.reduce((sum, entry) => sum + entry.calories, 0);
        const goalValue = loadProfile(args.user_id).calorie_goal;
        const goal = goalValue ? ` / ${goalValue} kcal goal` : "";
        const lines = [`${date} — ${total} kcal${goal}`, ""];
        for (const entry of dayEntries) lines.push(`${entry.time} [${entry.meal_type}] ${entry.meal}: ${entry.calories} kcal${entry.notes ? ` (${entry.notes})` : ""}`);
        return ok(lines.join("\n"));
      }

      if (action === "delete_food_entry") {
        const entries = loadFood(args.user_id);
        const before = entries.length;
        const remaining = entries.filter((entry) => {
          if (args.id) return entry.id !== args.id;
          if (args.meal) return !(entry.meal.toLowerCase().includes(String(args.meal).toLowerCase()) && (!args.date || entry.date === args.date));
          return true;
        });
        if (remaining.length === before) return ok("No matching entry found.");
        saveFood(args.user_id, remaining);
        return ok(`Deleted ${before - remaining.length} food entry/entries.`);
      }

      if (action === "log_weight") {
        if (args.weight_kg == null) return ok("log_weight requires weight_kg.");
        const health = loadHealth(args.user_id);
        health.weight.push({ date: today(), weight_kg: args.weight_kg, notes: args.notes });
        saveHealth(args.user_id, health);
        return ok(`Logged: ${args.weight_kg} kg`);
      }

      if (action === "get_weight_history") {
        const health = loadHealth(args.user_id);
        const days = args.days ?? 30;
        const cutoff = new Date();
        cutoff.setDate(cutoff.getDate() - days);
        const entries = health.weight.filter((entry) => entry.date >= cutoff.toISOString().slice(0, 10));
        if (!entries.length) return ok("No weight entries.");
        const lines = entries.map((entry) => `${entry.date}: ${entry.weight_kg} kg${entry.notes ? ` — ${entry.notes}` : ""}`);
        return ok(lines.join("\n"));
      }

      if (action === "log_workout") {
        if (!args.type || args.duration_minutes == null) return ok("log_workout requires type and duration_minutes.");
        const health = loadHealth(args.user_id);
        health.workouts.push({ id: Date.now().toString(36), date: today(), time: nowTime(), type: args.type, duration_minutes: args.duration_minutes, calories_burned: args.calories_burned, notes: args.notes });
        saveHealth(args.user_id, health);
        return ok(`Logged: ${args.type} for ${args.duration_minutes} min`);
      }

      if (action === "get_workout_history") {
        const health = loadHealth(args.user_id);
        const days = args.days ?? 14;
        const cutoff = new Date();
        cutoff.setDate(cutoff.getDate() - days);
        const entries = health.workouts.filter((entry) => entry.date >= cutoff.toISOString().slice(0, 10));
        if (!entries.length) return ok("No workouts recorded.");
        const totalMin = entries.reduce((sum, entry) => sum + entry.duration_minutes, 0);
        const lines = entries.map((entry) => `${entry.date} ${entry.time}: ${entry.type} ${entry.duration_minutes}min${entry.calories_burned ? ` / ${entry.calories_burned} kcal` : ""}${entry.notes ? ` — ${entry.notes}` : ""}`);
        lines.push(`\nTotal: ${entries.length} sessions, ${totalMin} min`);
        return ok(lines.join("\n"));
      }

      if (action === "log_water") {
        if (args.amount_ml == null) return ok("log_water requires amount_ml.");
        const health = loadHealth(args.user_id);
        health.water[today()] = (health.water[today()] ?? 0) + args.amount_ml;
        saveHealth(args.user_id, health);
        const total = health.water[today()];
        const goal = loadProfile(args.user_id).water_goal_ml ?? 2500;
        const pct = Math.round((total / goal) * 100);
        return ok(`Water logged: +${args.amount_ml}ml → ${total}ml today (${pct}% of ${goal}ml goal)`);
      }

      if (action === "define_habit") {
        if (!args.name) return ok("define_habit requires name.");
        const data = loadHabits(args.user_id);
        const key = String(args.name).toLowerCase();
        data.habits[key] = { description: args.description, frequency: args.frequency ?? "daily", created: today() };
        saveHabits(args.user_id, data);
        return ok(`Habit "${args.name}" created.`);
      }

      if (action === "log_habit") {
        if (!args.habit) return ok("log_habit requires habit.");
        const data = loadHabits(args.user_id);
        const key = String(args.habit).toLowerCase();
        if (!data.habits[key]) return ok(`Habit "${args.habit}" not found.`);
        const alreadyToday = data.logs.some((entry) => entry.habit === key && entry.date === today());
        if (alreadyToday) return ok(`"${args.habit}" already logged today.`);
        data.logs.push({ habit: key, date: today(), notes: args.notes });
        saveHabits(args.user_id, data);
        const streak = calcStreak(data.logs, key);
        return ok(`✓ ${args.habit} logged. Current streak: ${streak} day${streak !== 1 ? "s" : ""}.`);
      }

      if (action === "get_habit_stats") {
        const data = loadHabits(args.user_id);
        if (!Object.keys(data.habits).length) return ok("No habits defined yet.");
        const days = args.days ?? 30;
        const cutoff = new Date();
        cutoff.setDate(cutoff.getDate() - days);
        const cutoffStr = cutoff.toISOString().slice(0, 10);
        const habits = args.habit ? [String(args.habit).toLowerCase()] : Object.keys(data.habits);
        const lines: string[] = [];
        for (const key of habits) {
          const def = data.habits[key];
          if (!def) {
            lines.push(`"${key}" not found.`);
            continue;
          }
          const streak = calcStreak(data.logs, key);
          const recent = data.logs.filter((entry) => entry.habit === key && entry.date >= cutoffStr);
          lines.push(`${key}: streak ${streak}d | ${recent.length}/${days} days logged`);
        }
        return ok(lines.join("\n"));
      }

      return ok(`Unknown ha_health action: ${action}`);
    },
  } as any);
}
