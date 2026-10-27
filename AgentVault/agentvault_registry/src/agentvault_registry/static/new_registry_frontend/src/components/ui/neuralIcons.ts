/**
 * The name -> icon table behind <NeuralIcon name="...">.
 *
 * Every icon is a NAMED import from @lucide/vue, so the bundle carries these 122 and no others (the component
 * used to `import * as LucideIcons`, which put the whole set into the entry chunk: 1,635 icons in lucide-vue-next
 * 0.542, 1,854 in @lucide/vue 1.48). A name that is not in this table renders NEURAL_ICON_FALLBACK, the help
 * circle; neuralIcons.test.ts holds every name here, and every name a template passes, to an icon of its own.
 *
 * Several names are lucide's older aliases (HelpCircle, CheckCircle, AlertTriangle, Edit3, Loader2, ...), kept so
 * this list reads like the map it replaces; each is still exported by @lucide/vue 1.48. Five take lucide's own
 * `...Icon` spelling because the plain name is a JS or DOM global this module would otherwise shadow
 * (ClipboardIcon, FileIcon, HistoryIcon, LockIcon, MapIcon).
 */
import type { Component } from 'vue'
import {
  Activity, AlertCircle, AlertTriangle, Archive, ArrowDown, ArrowLeft, ArrowRight, ArrowUp, ArrowUpDown, AtSign,
  Award, BarChart3, Bell, Binary, BookOpen, Bot, Building2, Calendar, CandlestickChart, Check, CheckCircle,
  ChevronDown, ChevronLeft, ChevronRight, ChevronUp, Circle, CircleOff, ClipboardIcon, Clock, Cloud, Code, Coins,
  Command, Copy, Cpu, CreditCard, Crown, Database, DollarSign, Download, Edit3, ExternalLink, Eye, EyeOff, FileIcon,
  FileText, Filter, FlaskConical, Folder, GitBranch, Globe, Grid3x3, HardDrive, Hash, HelpCircle, HistoryIcon, Home,
  Import, Info, Key, Landmark, Layers, LayoutGrid, LineChart, List, Loader2, LockIcon, LogIn, LogOut, Mail, MapIcon,
  Maximize2, Medal, Menu, MessageCircle, MessageSquare, Minimize2, Monitor, MoreVertical, Network, Package, Pause,
  Play, Plug, Plus, PlusCircle, Radio, RefreshCw, Rocket, Save, Scale, Search, Server, Settings, Share2, Shield,
  ShieldCheck, Shuffle, Square, Star, Terminal, TestTube, Timer, Trash2, TrendingDown, TrendingUp, Trophy, Unlock,
  Upload, User, UserCheck, UserMinus, UserPlus, Users, Wallet, Webhook, Wifi, WifiOff, Wrench, X, XCircle, Zap,
} from '@lucide/vue'

export const NEURAL_ICONS: Readonly<Record<string, Component>> = {
  // Navigation & Core
  'dashboard': LayoutGrid,
  'mission-control': Cpu,
  'agents': Bot,
  'discovery': Search,
  'my-agents': Package,
  'organizations': Building2,
  'contracts': FileText,
  'disputes': AlertTriangle,
  'galactic-map': MapIcon,
  'senate-floor': Users,
  'federation': Network,
  'agent-builder': Wrench,
  'onboarding': Rocket,
  'staking': Coins,
  'webhooks': Webhook,
  'documentation': BookOpen,
  'support': HelpCircle,
  'logout': LogOut,
  'login': LogIn,

  // Status Icons
  'online': Circle,
  'offline': CircleOff,
  'active': Activity,
  'inactive': Pause,
  'connected': Wifi,
  'disconnected': WifiOff,
  'success': CheckCircle,
  'error': XCircle,
  'warning': AlertCircle,
  'info': Info,
  'pending': Clock,
  'loading': Loader2,

  // Actions
  'add': Plus,
  'create': PlusCircle,
  'edit': Edit3,
  'delete': Trash2,
  'save': Save,
  'cancel': X,
  'close': X,
  'refresh': RefreshCw,
  'download': Download,
  'upload': Upload,
  'export': Share2,
  'import': Import,
  'copy': Copy,
  'settings': Settings,
  'filter': Filter,
  'sort': ArrowUpDown,
  'search': Search,
  'view': Eye,
  'hide': EyeOff,
  'expand': Maximize2,
  'collapse': Minimize2,
  'menu': Menu,
  'more': MoreVertical,

  // System & Metrics
  'cpu': Cpu,
  'bot': Bot,
  'memory': HardDrive,
  'database': Database,
  'api': Terminal,
  'network': Activity,
  'performance': Zap,
  'analytics': BarChart3,
  'metrics': TrendingUp,
  'monitor': Monitor,
  'shield': Shield,
  'lock': LockIcon,
  'unlock': Unlock,
  'key': Key,
  'certificate': Award,

  // Communication
  'message': MessageSquare,
  'mail': Mail,
  'notification': Bell,
  'alert': AlertTriangle,
  'broadcast': Radio,

  // Navigation
  'arrow-left': ArrowLeft,
  'arrow-right': ArrowRight,
  'arrow-up': ArrowUp,
  'arrow-down': ArrowDown,
  'chevron-left': ChevronLeft,
  'chevron-right': ChevronRight,
  'chevron-up': ChevronUp,
  'chevron-down': ChevronDown,
  'external-link': ExternalLink,

  // Data & Files
  'file': FileIcon,
  'folder': Folder,
  'archive': Archive,
  'code': Code,
  'binary': Binary,
  'hash': Hash,
  'git': GitBranch,

  // Finance & Trading
  'wallet': Wallet,
  'credit-card': CreditCard,
  'dollar': DollarSign,
  'chart': LineChart,
  'candles': CandlestickChart,
  'trending-up': TrendingUp,
  'trending-down': TrendingDown,

  // Time
  'calendar': Calendar,
  'clock': Clock,
  'timer': Timer,
  'history': HistoryIcon,

  // User
  'user': User,
  'users': Users,
  'user-plus': UserPlus,
  'user-minus': UserMinus,
  'user-check': UserCheck,

  // Misc
  'globe': Globe,
  'server': Server,
  'cloud': Cloud,
  'command': Command,
  'layers': Layers,
  'grid': Grid3x3,
  'list': List,
  'play': Play,
  'pause': Pause,
  'stop': Square,
  'zap': Zap,
  'star': Star,
  'message-circle': MessageCircle,
  'check-circle': CheckCircle,
  'x-circle': XCircle,
  'alert-circle': AlertCircle,
  'trophy': Trophy,
  'medal': Medal,
  'award': Award,

  // Names the templates pass that the list above never had. Until §DEPS FE 3f the component looked every
  // name up in the whole icon set, PascalCasing only HYPHENATED names, so these one-word ones stayed
  // lowercase, missed, and drew the help-circle fallback ('flask' would have missed anyway: lucide has no
  // plain flask, FlaskConical is its lab flask).
  'activity': Activity,
  'check': Check,
  'clipboard': ClipboardIcon,
  'coins': Coins,
  'crown': Crown,
  'flask': FlaskConical,
  'home': Home,
  'landmark': Landmark,
  'plug': Plug,
  'plus': Plus,
  'scale': Scale,
  'shuffle': Shuffle,
  'terminal': Terminal,
  'webhook': Webhook,
  'x': X,

  // ...and the hyphenated ones that same whole-set lookup resolved by PascalCase.
  'alert-triangle': AlertTriangle,
  'at-sign': AtSign,
  'book-open': BookOpen,
  'log-in': LogIn,
  'refresh-cw': RefreshCw,
  'shield-check': ShieldCheck,
  'test-tube': TestTube,
  'trash-2': Trash2,
}

export const NEURAL_ICON_NAMES: readonly string[] = Object.keys(NEURAL_ICONS)

export const NEURAL_ICON_FALLBACK: Component = HelpCircle

/** The icon for a name, or the fallback when the table does not have it (never an inherited Object member). */
export function resolveNeuralIcon(name: string): Component {
  return Object.prototype.hasOwnProperty.call(NEURAL_ICONS, name) ? NEURAL_ICONS[name] : NEURAL_ICON_FALLBACK
}
