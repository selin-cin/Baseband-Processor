// =============================================================================
// Module Name:    repetition_encoder
// Design Unit:    (15,1)-style repetition ENCODER (enrollment only)
// Standard:       SystemVerilog IEEE 1800-2012
//
// Pure combinational block. For one 15-bit PUF chunk:
//   r_rep_o = message_i[14]                       (the protected bit)
//   h_rep_o = {14{message_i[14]}} ^ message_i[13:0]   (helper)
//
// Used in BOTH modes by the fuzzy_extractor top:
//   enrollment    : r_rep_o is collected, h_rep_o goes to the NVM
//   reconstruction: h_rep_o is the re-derived helper h_rep' and r_rep_o the
//                   noisy candidate bit; both feed the repetition_decoder,
//                   which only compares against the stored helper and votes.
//
// enable_i comes from the fuzzy_extractor top; outputs are forced to zero
// when disabled. The top registers the outputs whenever it wants (they are
// valid in the same cycle as message_i).
// =============================================================================

module repetition_encoder (
    input  logic        enable_i,
    input  logic [14:0] message_i,
    output logic [13:0] h_rep_o,
    output logic        r_rep_o,
    output logic        done_o
);

    logic [13:0] h_enc;

    repetition_core u_enc_core (
        .in1_i ({14{message_i[14]}}),
        .in2_i (message_i[13:0]),
        .out_o (h_enc)
    );

    assign r_rep_o = enable_i ? message_i[14] : 1'b0;
    assign h_rep_o = enable_i ? h_enc         : 14'd0;
    assign done_o  = enable_i;

endmodule
