export default function RazorpayLogo({ className = 'h-7', showText = true, isLight = false }) {
  return (
    <div className={`flex items-center gap-2 select-none ${className}`}>
      {/* Razorpay Dual-Blade Geometric Emblem */}
      <svg
        viewBox="0 0 120 100"
        fill="none"
        xmlns="http://www.w3.org/2000/svg"
        className="h-7 w-7 shrink-0"
      >
        <path d="M10 82L38 18L38 82H10Z" fill={isLight ? "#0C2340" : "#0B2046"} />
        <path d="M34 82L82 18L54 82H34Z" fill="#2563EB" />
        <path d="M38 18L82 18L54 82L38 18Z" fill="#3B82F6" />
      </svg>

      {showText && (
        <div className="flex items-center leading-none font-sans">
          <span className={`text-[18px] font-black tracking-tight italic ${
            isLight ? 'text-[#1B1F36]' : 'text-white'
          }`}>
            Razorpay
          </span>
          <span className={`text-[16px] font-extrabold tracking-tight ml-1.5 ${
            isLight ? 'text-[#2563EB]' : 'text-transparent bg-clip-text bg-gradient-to-r from-blue-400 via-cyan-300 to-teal-200'
          }`}>
            Recovery
          </span>
        </div>
      )}
    </div>
  );
}
