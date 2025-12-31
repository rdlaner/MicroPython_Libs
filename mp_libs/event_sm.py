"""Event Driven State Machine

User:
* Implements theirs states by subclassing InterfaceState and implementing virtual methods
* Responsible for invoking their own transitions w/in the state fxn/class using transition API
* Registers their states with a state machine instance
* Define their own events by creating instances of the Event class or by subclassing it
* Initializes state machine
* Starts state machine
* Injects async events into state machine via process_event API

SM Runtime API:
* register_state
* process_event

State fxn/class template:
* Entry action
* Exit action
* Process event
* Transition

Initial basic implementation will have all transitions and all down streams entry/exit actions
occur in the same call stack up until a state is pending. Will work for simple cases, but more
complex will monopolize the CPU and explode stack. Eventually will want to create an actual
runtime for the state machine and let it process things serially in its own runtime context. This
also means that we'll need some sort of event queue.
Not thread safe.
"""
# Standard imports
try:
    from typing import Set, Optional, TypeVar, Generic, TYPE_CHECKING
except ImportError:
    TYPE_CHECKING = False

if not TYPE_CHECKING:
    # MicroPython runtime fallback - create dummy classes only when typing module not available
    def TypeVar(name, *args, **kwargs):  # type: ignore
        return None

    class Generic:  # type: ignore
        """Dummy Generic that returns object when subscripted"""
        def __getitem__(self, item):
            return object

    Generic = Generic()  # type: ignore

# Third party imports
from mp_libs import logging

# Local imports
try:
    from config import config  # type: ignore
except ImportError:
    config = {"logging_level": logging.INFO}

# Globals
logger: logging.Logger = logging.getLogger("SM")
logger.setLevel(config["logging_level"])

# Type variable for StateMachine subclasses
SMType = TypeVar('SMType', bound='StateMachine')


class Event():
    """Generic state machine Event"""
    def __init__(self, signal: int) -> None:
        self.signal = signal

    def __repr__(self) -> str:
        return str(self.signal)


class InterfaceState(Generic[SMType]):
    """Abstract base class intended to be implemented by inheriting state class

    Each state subclass is a singleton. This allows each state to refer to any other state when
    transitioning by invoking it directly, ie no need to track state instance references.
    """
    _instances = {}  # per-class singleton registry

    def __new__(cls, *args, **kwargs):
        """Make class a singleton"""
        if cls not in cls._instances:
            instance = super().__new__(cls)
            cls._instances[cls] = instance
        return cls._instances[cls]

    def __class_getitem__(cls, item):
        """Support subscripting for type hints like InterfaceState["PtpSM"]"""
        return cls

    def __init__(self, name: Optional[str] = None):
        """Make class a singleton"""
        if hasattr(self, "_initialized"):
            return
        self._initialized = True
        self._name = name
        self._sm: Optional[SMType] = None

    def __repr__(self) -> str:
        return self._name if self._name is not None else "NA"

    @property
    def sm(self) -> SMType:
        """Get parent state machine.

        Raises:
            RuntimeError: State is not registered with any state machine.

        Returns:
            SMType: State machine reference.
        """
        if self._sm is None:
            raise RuntimeError("State is not registered to a state machine")
        return self._sm

    def entry(self) -> None:
        """Function executed upon entry to this state.

        Raises:
            RuntimeError: Must be implemented by inheriting class.
        """
        raise RuntimeError("Must be implemented by inheriting class")

    def exit(self) -> None:
        """Function executed upon transitioning out of this state.

        Raises:
            RuntimeError: Must be implemented by inheriting class.
        """
        raise RuntimeError("Must be implemented by inheriting class")

    def process_evt(self, evt: Event) -> None:
        """Processes the passed state machine event.

        Args:
            evt (Event): State machine event.

        Raises:
            RuntimeError: Must be implemented by inheriting class.
        """
        raise RuntimeError("Must be implemented by inheriting class")

    def set_parent_sm(self, sm: SMType):
        """Set parent state machine reference.

        Args:
            sm (SMType): Parent state machine.
        """
        self._sm = sm

    def transition(self, new_state: 'InterfaceState[SMType]'):
        """Helper function to transition parent state machine to next desired state.

        Args:
            new_state (InterfaceState[SMType]): Next desired state.
        """
        self.sm.transition(self, new_state)


class StateMachine():
    """State Machine"""
    def __init__(self, name: str) -> None:
        self._name: str = name
        self._current_state: Optional[InterfaceState] = None
        self._states: Set[InterfaceState] = set()

    @property
    def current_state(self) -> Optional[InterfaceState]:
        """Get a reference to the state machine's current state

        Returns:
            InterfaceState: Current state
        """
        return self._current_state

    def process_evt(self, evt: Event):
        """Inject event to current state and allow it to process the event.

        Args:
            evt (Event): Event to process

        Raises:
            RuntimeError: State machine has not yet been started.
        """
        if self._current_state is None:
            raise RuntimeError("Can't process evt for SM that has not been started")

        self._current_state.process_evt(evt)

    def register_state(self, state: InterfaceState):
        """Register a new state with this state machine.

        Args:
            state (InterfaceState): New state to register.
        """
        self._states.add(state)
        state.set_parent_sm(self)

    def start(self, start_state: InterfaceState):
        """Start this state machine with the given state.

        Args:
            start_state (InterfaceState): State to start state machine with.
        """
        if start_state not in self._states:
            self.register_state(start_state)

        if self._current_state is not None:
            self._current_state.exit()

        self._current_state = start_state
        self._current_state.entry()

    def transition(self, curr_state: InterfaceState, new_state: InterfaceState):
        """Transition from the current state to a new state.

        NOTE: If new_state is not registered with this state machine, it will be auto registered.

        Args:
            curr_state (InterfaceState): Current state to transition from.
            new_state (InterfaceState): New state to transition to.

        Raises:
            RuntimeError: curr_state does not match actual current state.
        """
        if self._current_state != curr_state:
            raise RuntimeError("SM current state does not match active state")
        if new_state not in self._states:
            self.register_state(new_state)

        curr_state.exit()
        self._current_state = new_state
        self._current_state.entry()
