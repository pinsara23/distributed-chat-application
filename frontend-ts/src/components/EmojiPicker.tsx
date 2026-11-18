import { useState } from "react";

const CATEGORIES: { icon: string; label: string; items: string }[] = [
  { icon: "😀", label: "Smileys", items: "😀😃😄😁😆😅😂🤣🙂😉😊😇🥰😍🤩😘😗😚😙😋😛😜🤪😝🤗🤭🤔🤨😐😑😶🙄😏😒😞😔😟😕🙁😮😯😲😳🥺😢😭😤😠😡🤯😱😨😰😥😓🤤😴🥱😷🤒🤕🤢🤮🥵🥶😎🤓🧐" },
  { icon: "👍", label: "People", items: "👍👎👌✌️🤞🤟🤘🤙👈👉👆👇☝️✋🤚🖐️🖖👋🤝🙏💪👏🙌👐🤲✍️💅🧠👀👁️👅👄🫶❤️🧡💛💚💙💜🖤🤍💔💕💞💓💗💖💘💝" },
  { icon: "🐶", label: "Animals", items: "🐶🐱🐭🐹🐰🦊🐻🐼🐨🐯🦁🐮🐷🐸🐵🙈🙉🙊🐔🐧🐦🐤🦆🦉🦇🐺🐗🐴🦄🐝🐛🦋🐌🐞🐢🐍🐙🦑🦀🐠🐟🐬🐳🦈🐘🦒" },
  { icon: "🍕", label: "Food", items: "🍎🍐🍊🍋🍌🍉🍇🍓🍒🍑🥭🍍🥥🥝🍅🥑🥦🌽🥕🍞🥐🧀🍳🥞🥓🍗🍔🍟🌭🍕🥪🌮🌯🍜🍝🍣🍤🍦🍩🍪🎂🍰🍫🍬☕🍵🥤🍺🍷" },
  { icon: "⚽", label: "Activity", items: "⚽🏀🏈⚾🎾🏐🏉🎱🏓🏸🥊🥋🎯⛳🎣🎮🎲🧩🎨🎬🎤🎧🎹🥁🎸🎻🏆🥇🥈🥉🏅🎉🎊🎁🎈" },
  { icon: "🚀", label: "Travel", items: "🚗🚕🚌🚎🏎️🚓🚑🚒🚚🚲🛵🏍️🚂✈️🚀🛸🚁⛵🚢⚓🏠🏢🏰🗼🗽⛰️🌋🏝️🏖️🌅🌄🌃🌉" },
  { icon: "💡", label: "Objects", items: "⌚📱💻⌨️🖥️🖨️📷📹🎥📞📺📻⏰💡🔋🔌💰💳💎🔧🔨⚙️🔒🔑🛡️📦📚📝📌📎✂️🔍" },
  { icon: "✅", label: "Symbols", items: "✅❌⭕❗❓⚠️🔥✨⭐🌟💫💥💯🆗🆕🔔🔕➕➖➗✔️♻️🔴🟠🟡🟢🔵🟣⚫⚪" },
];

const split = (s: string): string[] => [...new Intl.Segmenter(undefined, { granularity: "grapheme" }).segment(s)].map((x) => x.segment);

export function EmojiPicker({ onPick }: { onPick: (emoji: string) => void }) {
  const [tab, setTab] = useState(0);
  return (
    <div className="emoji-picker" role="dialog" aria-label="Emoji picker">
      <div className="emoji-tabs" role="tablist">
        {CATEGORIES.map((c, i) => (
          <button key={c.label} type="button" role="tab" aria-selected={i === tab} title={c.label} onClick={() => setTab(i)}>{c.icon}</button>
        ))}
      </div>
      <div className="emoji-grid">
        {split(CATEGORIES[tab].items).map((e, i) => (
          <button key={`${tab}-${i}`} type="button" onClick={() => onPick(e)} aria-label={`Insert ${e}`}>{e}</button>
        ))}
      </div>
    </div>
  );
}
