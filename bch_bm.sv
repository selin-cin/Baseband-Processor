// =============================================================================
// Module Name:    bch_bm
// Design Unit:    Berlekamp-Massey (BM) Polynomial Solver Architecture
// Standard:       SystemVerilog IEEE 1800-2012
//
// Description:    Implements the iterative Berlekamp-Massey Algorithm tailored
//                 for a binary BCH (255, 139, 15) decoder over Galois Field
//                 GF(2^8). This hardware accelerator solves the key equation
//                 by processing 2*T syndrome components sequentially to compute
//                 the Error Locator Polynomial Lambda(x).
//
//                 Each algorithmic iteration is split across two clock cycles
//                 to break up the critical path: cycle 1 (DISC) resolves the
//                 discrepancy d_r via the T-term reduction and registers it;
//                 cycle 2 (UPDATE) consumes the registered discrepancy for the
//                 single remaining GF multiply per candidate coefficient and
//                 commits Lambda(x)/B(x)/L. No cycle chains two full
//                 variable-operand GF(2^8) multiplies.
//
// Mathematical Constraints:
//                 - Maximum error correction capability: T = 15
//                 - Exact execution latency per run: 4*T clock cycles
//                 - Total syndrome bytes processed: 2*T = 30 elements
// =============================================================================

module bch_bm
    import gf_math_pkg::*;
#(
    parameter integer T = 15 // Designates error correction capacity limit
)(
    input  logic       clk_i,          // Core functional clock system
    input  logic       rst_ni,         // Active-low asynchronous hardware reset
    input  logic       start_i,        // Synchronous pulse initiating calculation sequence
    input  logic [7:0] synd_i   [2*T], // 30-Byte structural array payload containing syndromes
    output logic [7:0] lambda_o [T+1], // Solved Error Locator Polynomial Lambda(x) coefficients
    output logic [7:0] l_degree_o,     // Code block error count
    output logic       done_o          // 1-cycle pulse: results ready
);

    // --- Hardwired Algorithmic Bounds ---
    localparam integer ITER = 2*T; // Exact calculation iteration limit (30 iterations)

    // --- Core Architecture Internal Registers ---
    logic [7:0] synd_r [0:2*T-1]; // Latch the syndrome input
    logic [7:0] Lambda [T+1];     // Tracks current architectural state of Lambda(x)
    logic [7:0] B      [T+1];     // Correction / Discrepancy history scratchpad polynomial, B(x)
    logic [7:0] L_len;            // Registers current dynamic estimate of code block error count
    logic [7:0] L_len_next;       // Next state logic for code block error count
    logic [7:0] bm_cnt;           // Sequential iteration engine step tracking counter
    logic       running;          // Active execution state machine indicator bit
    logic       phase_q;          // 0 = DISC (resolve discrepancy), 1 = UPDATE (apply it)

    // --- Pipeline Register: Discrepancy Resolved in the DISC Phase ---
    logic [7:0] delta_q;

    // --- Pure Combinational Bus Networks ---
    logic [7:0] bm_delta_c;             // DISC-phase discrepancy candidate (d_r), from Lambda/synd_r
    logic [7:0] bm_Lambda_new_c [T+1];  // UPDATE-phase look-ahead Lambda(x) candidate, from delta_q
    logic       b_update_c;             // UPDATE-phase B(x) branch decision, from delta_q

    // =========================================================================
    // 1a. DISC PHASE NETWORK: Discrepancy Resolution (single GF-mul depth,
    //     T-term reduction) -- registers into delta_q.
    // =========================================================================
    always_comb begin
        bm_delta_c = synd_r[bm_cnt];
        for (int j = 1; j <= T; j = j + 1) begin
            if (bm_cnt >= 8'(j)) begin
                bm_delta_c = bm_delta_c ^ gf_mul(Lambda[j], synd_r[bm_cnt - 8'(j)]);
            end
        end
    end

    // =========================================================================
    // 1b. UPDATE PHASE NETWORK: Candidate Lambda(x) and B(x) Branch Decision
    //     (single GF-mul depth each) -- consumes the registered delta_q.
    // =========================================================================
    always_comb begin
        bm_Lambda_new_c[0] = Lambda[0];
        for (int j = 1; j <= T; j = j + 1) begin
            bm_Lambda_new_c[j] = Lambda[j] ^ gf_mul(delta_q, B[j-1]);
        end

        b_update_c = ((L_len << 1) <= bm_cnt) && (delta_q != 8'h00);
        L_len_next = b_update_c ? (bm_cnt + 8'h01 - L_len) : L_len;
    end

    // =========================================================================
    // 2. SYNCHRONOUS REGISTER PIPELINE: Control State Machine & History Shift
    // =========================================================================
    always_ff @(posedge clk_i or negedge rst_ni) begin
        if (!rst_ni) begin
            // Synchronous Reset: Drive system vectors to safe initial clear boundaries
            running    <= 1'b0;
            phase_q    <= 1'b0;
            done_o     <= 1'b0;
            l_degree_o <= 8'd0;
            bm_cnt     <= 8'd0;
            L_len      <= 8'd0;
            delta_q    <= 8'h00;
            for (int i = 0; i <= T; i++) begin
                Lambda[i]   <= 8'h00;
                B[i]        <= 8'h00;
                lambda_o[i] <= 8'h00;
            end
        end
        else begin
            // Default Assignment: Enforce done status strobe to drop after a single clock cycle pulse
            done_o <= 1'b0;

            // Trigger State: Capture startup request if processing engine sits idle
            if (start_i && !running) begin
                running   <= 1'b1;
                phase_q   <= 1'b0;
                bm_cnt    <= 8'd0;
                L_len     <= 8'd0;
                delta_q   <= 8'h00;

                // Initialize base matrices according to BCH decoding theory requirements
                Lambda[0] <= 8'h01; // Base scalar value constant
                B[0]      <= 8'h01; // Base operational tracker seed

                for (int i = 1; i <= T; i++) begin
                    Lambda[i] <= 8'h00;
                    B[i]      <= 8'h00;
                end

                for (int i = 0; i < 2*T; i++) begin
                    synd_r[i] <= synd_i[i];
                end
            end
            // Processing State: Execution core loop tracking
            else if (running) begin

                if (!phase_q) begin
                    // DISC: latch the resolved discrepancy, move to UPDATE next cycle
                    delta_q <= bm_delta_c;
                    phase_q <= 1'b1;
                end
                else begin
                    // UPDATE: commit look-ahead Lambda(x), branch B(x), advance the iteration
                    for (int i = 0; i <= T; i++) begin
                        Lambda[i] <= bm_Lambda_new_c[i];
                    end

                    if (b_update_c) begin
                        // Math: B_next(x) = (d_r ^ -1) * Lambda_current(x)
                        for (int i = 0; i <= T; i++) begin
                            B[i] <= gf_mul(gf_inv(delta_q), Lambda[i]);
                        end
                    end
                    else begin
                        for (int i = T; i > 0; i = i - 1) begin
                            B[i] <= B[i-1];
                        end
                        B[0] <= 8'h00; // Zero padding lower bound element to support shift order rise
                    end

                    // Math: Dynamic Error Degree estimate update: L = r + 1 - L
                    L_len   <= L_len_next;

                    // Step iteration loop sequence counter advance
                    bm_cnt  <= bm_cnt + 8'h01;
                    phase_q <= 1'b0;

                    // --- Decoupled Termination & Handshake Verification ---
                    // Triggers when step count matches absolute iteration run limit boundary (30 cycles)
                    if (bm_cnt == 8'(ITER - 1)) begin
                        running    <= 1'b0; // Shutdown engine run bit loop
                        done_o     <= 1'b1; // Raise interface status completion pulse
                        l_degree_o <= L_len_next;

                        // Route synthesized coefficients out to external top integration layer
                        for (int i = 0; i <= T; i++) begin
                            lambda_o[i] <= bm_Lambda_new_c[i];
                        end
                    end
                end
            end
        end
    end

endmodule
